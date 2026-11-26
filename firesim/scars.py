"""Render-neutral burn masks. Rows run south to north in simulation coordinates."""
from .sparse import SparseFireSim


def burn_tiles(sim, tile_cells=32):
    """Return only changed tiles, with one 8-bit fuel-loss value per cell."""
    if type(tile_cells) is not int or not 1 <= tile_cells <= 256:
        raise ValueError("Invalid burn mask tile size")
    cells = sim.cells.allocated.items() if isinstance(sim, SparseFireSim) else enumerate(sim.cells)
    tiles = {}
    for index, cell in cells:
        if cell.initial_fuel <= 0 or cell.fuel >= cell.initial_fuel:
            continue
        severity = min(255, round(255 * (1 - cell.fuel / cell.initial_fuel)))
        if not severity:
            continue
        x, y = index % sim.width, index // sim.width
        tx, offset_x = divmod(x, tile_cells)
        ty, offset_y = divmod(y, tile_cells)
        key = (tx, ty)
        if key not in tiles:
            tiles[key] = bytearray(tile_cells ** 2)
        tiles[key][offset_y * tile_cells + offset_x] = severity
    return {key: bytes(tiles[key]) for key in sorted(tiles)}
