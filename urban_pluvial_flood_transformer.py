"""
Research-oriented PyTorch prototype for urban pluvial flooding prediction.

This script implements an end-to-end spatiotemporal inundation prediction model
based on a geography-aware attention mechanism. It follows the requested
methodological structure:

1. Input embedding layer
2. Geography-aware Transformer encoder
3. Output mapping layer

The implementation includes:
- InputEmbedding
- TemporalEmbedding
- GeographyAwareMultiHeadAttention
- TransformerEncoderBlock
- GeographyAwareFloodTransformer
- A supervised training loop demonstration
- A grid-to-road aggregation function

The script is fully runnable with dummy data to demonstrate:
- expected tensor shapes
- forward pass
- loss calculation
- one training epoch
- road-segment disturbance aggregation
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class ModelConfig:
    """Container for model hyperparameters used in the demo."""

    rainfall_dim: int
    inundation_dim: int
    static_dim: int
    hidden_dim: int
    num_heads: int
    num_layers: int
    time_window: int
    dropout: float = 0.1


class InputEmbedding(nn.Module):
    """
    Multi-source input embedding module.

    Methodological correspondence:
    - The model receives three input sources:
      1) rainfall process over a time window
      2) historical inundation sequence
      3) static environmental features
    - These variables are concatenated and linearly projected into a unified
      hidden feature space, exactly as required in the description.

    Input shapes:
    - rainfall: [B, T, N, Fr]
    - inundation_history: [B, T, N, Fi]
    - static_features: [B, N, Fs] or [B, T, N, Fs]

    Output shape:
    - embedded features: [B, T, N, D]
    """

    def __init__(self, rainfall_dim: int, inundation_dim: int, static_dim: int, hidden_dim: int):
        super().__init__()
        input_dim = rainfall_dim + inundation_dim + static_dim
        self.proj = nn.Linear(input_dim, hidden_dim)

    def forward(
        self,
        rainfall: torch.Tensor,
        inundation_history: torch.Tensor,
        static_features: torch.Tensor,
    ) -> torch.Tensor:
        batch_size, time_steps, num_grids, _ = rainfall.shape

        # If static features do not already have a time dimension, broadcast them
        # across the full historical window so every time step has access to the
        # same environmental descriptors.
        if static_features.dim() == 3:
            static_features = static_features.unsqueeze(1).expand(batch_size, time_steps, num_grids, -1)
        elif static_features.dim() != 4:
            raise ValueError("static_features must have shape [B, N, Fs] or [B, T, N, Fs]")

        # Concatenate all source variables before linear projection, matching the
        # required unified embedding strategy.
        x = torch.cat([rainfall, inundation_history, static_features], dim=-1)
        return self.proj(x)


class TemporalEmbedding(nn.Module):
    """
    Learnable temporal embedding.

    Methodological correspondence:
    - Temporal embeddings are added after the input projection so the model can
      distinguish the order of observations within the time window.

    Input:
    - x: [B, T, N, D]

    Output:
    - x + temporal_embedding: [B, T, N, D]
    """

    def __init__(self, max_time_steps: int, hidden_dim: int):
        super().__init__()
        self.embedding = nn.Embedding(max_time_steps, hidden_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        _, time_steps, _, _ = x.shape
        time_index = torch.arange(time_steps, device=x.device)
        temporal_feature = self.embedding(time_index).view(1, time_steps, 1, -1)
        return x + temporal_feature


class GeographyAwareMultiHeadAttention(nn.Module):
    """
    Geography-aware multi-head attention over spatial units.

    Methodological correspondence:
    - This is the key innovation layer.
    - Attention is computed among grid cells for each time step.
    - A spatial constraint matrix S is injected into attention logits before
      softmax, which suppresses information exchange between cells that are not
      physically connected.
    - S can encode adjacency, hydrological connectivity, and terrain constraints.

    Design choice for this prototype:
    - For each time step independently, the grid cells [N] act as the tokens.
    - The feature vector for each cell is the hidden embedding D.
    - This makes the geography-aware attention naturally operate over space.

    Input:
    - x: [B, T, N, D]
    - spatial_constraint: [N, N]

    Output:
    - attended features: [B, T, N, D]
    """

    def __init__(self, hidden_dim: int, num_heads: int, dropout: float = 0.1):
        super().__init__()
        if hidden_dim % num_heads != 0:
            raise ValueError("hidden_dim must be divisible by num_heads")

        self.hidden_dim = hidden_dim
        self.num_heads = num_heads
        self.head_dim = hidden_dim // num_heads

        self.q_proj = nn.Linear(hidden_dim, hidden_dim)
        self.k_proj = nn.Linear(hidden_dim, hidden_dim)
        self.v_proj = nn.Linear(hidden_dim, hidden_dim)
        self.out_proj = nn.Linear(hidden_dim, hidden_dim)

        self.attn_dropout = nn.Dropout(dropout)
        self.out_dropout = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor, spatial_constraint: torch.Tensor) -> torch.Tensor:
        batch_size, time_steps, num_grids, hidden_dim = x.shape
        if spatial_constraint.shape != (num_grids, num_grids):
            raise ValueError(
                f"spatial_constraint must have shape [{num_grids}, {num_grids}], "
                f"but got {tuple(spatial_constraint.shape)}"
            )

        # Merge batch and time so attention is applied over spatial units N for
        # every time slice independently.
        x = x.reshape(batch_size * time_steps, num_grids, hidden_dim)

        q = self.q_proj(x)
        k = self.k_proj(x)
        v = self.v_proj(x)

        q = q.view(batch_size * time_steps, num_grids, self.num_heads, self.head_dim).transpose(1, 2)
        k = k.view(batch_size * time_steps, num_grids, self.num_heads, self.head_dim).transpose(1, 2)
        v = v.view(batch_size * time_steps, num_grids, self.num_heads, self.head_dim).transpose(1, 2)

        # Standard scaled dot-product attention logits.
        attn_logits = torch.matmul(q, k.transpose(-2, -1)) / math.sqrt(self.head_dim)

        # Geography-aware logit bias / mask injection:
        # - positive entries of S can be seen as stronger connectivity
        # - zero or negative entries can represent no physical connection
        # Non-connected cell pairs receive a large negative bias so their
        # attention weights become nearly zero after softmax.
        connectivity_mask = spatial_constraint > 0
        additive_bias = spatial_constraint.clone().to(attn_logits.dtype)
        additive_bias = additive_bias.unsqueeze(0).unsqueeze(0)  # [1, 1, N, N]
        attn_logits = attn_logits + additive_bias
        attn_logits = attn_logits.masked_fill(~connectivity_mask.unsqueeze(0).unsqueeze(0), -1e9)

        attn_weights = F.softmax(attn_logits, dim=-1)
        attn_weights = self.attn_dropout(attn_weights)

        attended = torch.matmul(attn_weights, v)
        attended = attended.transpose(1, 2).contiguous().view(batch_size * time_steps, num_grids, hidden_dim)
        attended = self.out_proj(attended)
        attended = self.out_dropout(attended)

        return attended.view(batch_size, time_steps, num_grids, hidden_dim)


class TransformerEncoderBlock(nn.Module):
    """
    Geography-aware Transformer encoder block.

    Methodological correspondence:
    - Each encoder layer contains:
      1) geography-aware multi-head attention
      2) feed-forward network
      3) residual connections
      4) layer normalization
    - This module directly instantiates that requested block structure.
    """

    def __init__(self, hidden_dim: int, num_heads: int, dropout: float = 0.1, ff_multiplier: int = 4):
        super().__init__()
        self.attention = GeographyAwareMultiHeadAttention(hidden_dim, num_heads, dropout)
        self.norm1 = nn.LayerNorm(hidden_dim)
        self.norm2 = nn.LayerNorm(hidden_dim)

        self.ffn = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim * ff_multiplier),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim * ff_multiplier, hidden_dim),
            nn.Dropout(dropout),
        )

    def forward(self, x: torch.Tensor, spatial_constraint: torch.Tensor) -> torch.Tensor:
        # Residual connection around geography-aware attention.
        x = self.norm1(x + self.attention(x, spatial_constraint))

        # Residual connection around position-wise feed-forward network.
        x = self.norm2(x + self.ffn(x))
        return x


class GeographyAwareFloodTransformer(nn.Module):
    """
    Complete end-to-end flood prediction framework.

    Methodological correspondence:
    - Input embedding layer
    - Stacked geography-aware Transformer encoder with 3 layers
    - Output mapping layer

    Prediction target:
    - Next-step inundation depth at grid scale: [B, N, 1]

    Prototype design:
    - After encoding the full time window, the final time-step hidden state
      summarizes the most recent spatiotemporal context for each grid cell.
    - A linear mapping projects each cell representation to the next-step water
      depth.
    """

    def __init__(self, config: ModelConfig):
        super().__init__()
        self.input_embedding = InputEmbedding(
            rainfall_dim=config.rainfall_dim,
            inundation_dim=config.inundation_dim,
            static_dim=config.static_dim,
            hidden_dim=config.hidden_dim,
        )
        self.temporal_embedding = TemporalEmbedding(config.time_window, config.hidden_dim)
        self.input_dropout = nn.Dropout(config.dropout)

        self.encoder_layers = nn.ModuleList(
            [
                TransformerEncoderBlock(
                    hidden_dim=config.hidden_dim,
                    num_heads=config.num_heads,
                    dropout=config.dropout,
                )
                for _ in range(config.num_layers)
            ]
        )

        self.output_head = nn.Linear(config.hidden_dim, 1)

    def forward(
        self,
        rainfall: torch.Tensor,
        inundation_history: torch.Tensor,
        static_features: torch.Tensor,
        spatial_constraint: torch.Tensor,
    ) -> torch.Tensor:
        x = self.input_embedding(rainfall, inundation_history, static_features)
        x = self.temporal_embedding(x)
        x = self.input_dropout(x)

        for layer in self.encoder_layers:
            x = layer(x, spatial_constraint)

        # Use the final time step representation to forecast the next-step
        # inundation depth for each grid cell.
        last_hidden = x[:, -1, :, :]  # [B, N, D]
        next_depth = self.output_head(last_hidden)  # [B, N, 1]
        return next_depth


def aggregate_grid_to_road_segments(
    grid_depth: torch.Tensor,
    road_grid_mapping: torch.Tensor,
    reduction: str = "mean",
) -> torch.Tensor:
    """
    Aggregate grid-scale inundation depth to road-segment disturbance values.

    Methodological correspondence:
    - After grid-scale prediction, a spatial aggregation operator converts grid
      inundation results into road-segment-scale disturbance indicators.

    Inputs:
    - grid_depth: [B, N, 1] predicted next-step grid water depth
    - road_grid_mapping: [R, N] aggregation weights from grids to road segments
      Example:
      - binary mask for membership
      - normalized overlap weights
      - road-grid influence coefficients
    - reduction:
      - "mean": weighted mean inundation on each road segment
      - "sum": weighted accumulation
      - "max": max depth among linked grids

    Output:
    - road_disturbance: [B, R, 1]
    """

    if grid_depth.dim() != 3 or grid_depth.size(-1) != 1:
        raise ValueError("grid_depth must have shape [B, N, 1]")
    if road_grid_mapping.dim() != 2:
        raise ValueError("road_grid_mapping must have shape [R, N]")

    batch_size, num_grids, _ = grid_depth.shape
    num_roads, mapped_grids = road_grid_mapping.shape
    if num_grids != mapped_grids:
        raise ValueError("road_grid_mapping second dimension must match number of grids")

    grid_values = grid_depth.squeeze(-1)  # [B, N]
    weights = road_grid_mapping.to(grid_depth.device, dtype=grid_depth.dtype)

    if reduction == "sum":
        road_values = torch.einsum("rn,bn->br", weights, grid_values)
    elif reduction == "mean":
        numerator = torch.einsum("rn,bn->br", weights, grid_values)
        denominator = weights.sum(dim=-1).clamp_min(1e-6).unsqueeze(0)
        road_values = numerator / denominator
    elif reduction == "max":
        expanded_grid = grid_values.unsqueeze(1).expand(batch_size, num_roads, num_grids)
        road_mask = weights.unsqueeze(0) > 0
        road_values = expanded_grid.masked_fill(~road_mask, float("-inf")).max(dim=-1).values
        road_values = torch.where(torch.isfinite(road_values), road_values, torch.zeros_like(road_values))
    else:
        raise ValueError("reduction must be one of: 'mean', 'sum', 'max'")

    return road_values.unsqueeze(-1)


def build_dummy_spatial_constraint(num_grids: int) -> torch.Tensor:
    """
    Build a simple example spatial constraint matrix S.

    For the demo:
    - self-connections are allowed
    - nearby cells are connected
    - far cells are disconnected
    - small positive weights reflect relative physical connectivity strength
    """

    spatial_constraint = torch.zeros(num_grids, num_grids)
    for i in range(num_grids):
        for j in range(num_grids):
            distance = abs(i - j)
            if distance == 0:
                spatial_constraint[i, j] = 1.0
            elif distance == 1:
                spatial_constraint[i, j] = 0.7
            elif distance == 2:
                spatial_constraint[i, j] = 0.3
            else:
                spatial_constraint[i, j] = 0.0
    return spatial_constraint


def build_dummy_road_mapping(num_roads: int, num_grids: int) -> torch.Tensor:
    """
    Create a simple road-to-grid mapping matrix for demonstration.

    Each road segment is associated with a subset of grid cells.
    Values can be interpreted as overlap or influence weights.
    """

    mapping = torch.zeros(num_roads, num_grids)
    grids_per_road = max(1, num_grids // num_roads)
    for road_idx in range(num_roads):
        start = road_idx * grids_per_road
        end = min(num_grids, start + grids_per_road + 1)
        mapping[road_idx, start:end] = 1.0
    return mapping


def run_training_demo() -> None:
    """
    End-to-end demonstration with dummy data.

    This function shows:
    - model input shapes
    - forward pass
    - supervised loss calculation
    - one training epoch using dummy SWMM-like labels
    - grid-to-road aggregation
    """

    torch.manual_seed(42)

    # Shape assumptions from the request.
    B = 4   # batch size
    T = 6   # time window
    N = 12  # number of grid cells
    Fr = 3  # rainfall feature dimension
    Fi = 2  # inundation-state feature dimension
    Fs = 4  # static feature dimension
    D = 32  # hidden dimension
    R = 5   # number of road segments for aggregation demo

    config = ModelConfig(
        rainfall_dim=Fr,
        inundation_dim=Fi,
        static_dim=Fs,
        hidden_dim=D,
        num_heads=4,
        num_layers=3,  # exactly as requested
        time_window=T,
        dropout=0.1,
    )

    model = GeographyAwareFloodTransformer(config)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    criterion = nn.MSELoss()

    # Dummy inputs following the required organization.
    rainfall = torch.randn(B, T, N, Fr)
    inundation_history = torch.randn(B, T, N, Fi)
    static_features = torch.randn(B, N, Fs)

    # Dummy labels representing next-step inundation depth generated by a
    # hydrodynamic simulator such as SWMM.
    target_next_depth = torch.randn(B, N, 1)

    # Geography-aware spatial constraint matrix S.
    spatial_constraint = build_dummy_spatial_constraint(N)

    # Road mapping matrix for post-processing.
    road_grid_mapping = build_dummy_road_mapping(R, N)

    print("=" * 80)
    print("Urban pluvial flooding prototype demo")
    print("=" * 80)
    print(f"rainfall shape:             {tuple(rainfall.shape)}")
    print(f"inundation_history shape:   {tuple(inundation_history.shape)}")
    print(f"static_features shape:      {tuple(static_features.shape)}")
    print(f"spatial_constraint shape:   {tuple(spatial_constraint.shape)}")
    print(f"target_next_depth shape:    {tuple(target_next_depth.shape)}")
    print()

    # Forward pass demonstration.
    model.train()
    prediction = model(
        rainfall=rainfall,
        inundation_history=inundation_history,
        static_features=static_features,
        spatial_constraint=spatial_constraint,
    )
    loss = criterion(prediction, target_next_depth)

    print(f"prediction shape:           {tuple(prediction.shape)}")
    print(f"initial loss:               {loss.item():.6f}")
    print()

    # One supervised training epoch on dummy data.
    print("Running one training epoch...")
    optimizer.zero_grad()
    loss.backward()
    optimizer.step()

    with torch.no_grad():
        updated_prediction = model(
            rainfall=rainfall,
            inundation_history=inundation_history,
            static_features=static_features,
            spatial_constraint=spatial_constraint,
        )
        updated_loss = criterion(updated_prediction, target_next_depth)

    print(f"loss after one epoch:       {updated_loss.item():.6f}")
    print()

    # Grid-to-road aggregation demo.
    road_disturbance = aggregate_grid_to_road_segments(
        grid_depth=updated_prediction,
        road_grid_mapping=road_grid_mapping,
        reduction="mean",
    )
    print(f"road_grid_mapping shape:    {tuple(road_grid_mapping.shape)}")
    print(f"road_disturbance shape:     {tuple(road_disturbance.shape)}")
    print()
    print("Sample grid prediction for batch 0 (first 5 grids):")
    print(updated_prediction[0, :5, 0])
    print()
    print("Sample road disturbance for batch 0:")
    print(road_disturbance[0, :, 0])


if __name__ == "__main__":
    run_training_demo()
