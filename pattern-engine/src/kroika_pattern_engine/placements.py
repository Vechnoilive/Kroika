"""Place details in the original coordinate frame of the final cut pieces."""

from .attachments import descendants
from .blocks import BlockConstructionError
from .geometry import BoundingBox, contour_from_data


def placement_frame(pattern, root, source):
    pieces = descendants(pattern, root)
    if not pieces:
        raise BlockConstructionError(
            'DETAIL_TARGET_MISSING', 'Нет итоговых деталей для выбранного расположения.',
            f'/garment_spec/design_intent/elements/{source}',
        )
    boxes = [contour_from_data(p['seam_contour']).bounding_box for p in pieces]
    return pieces, BoundingBox(
        min(b.min_x_mm for b in boxes), min(b.min_y_mm for b in boxes),
        max(b.max_x_mm for b in boxes), max(b.max_y_mm for b in boxes),
    )


def containing_piece(pieces, edges, source):
    """A pocket opening needs one continuous piece; never silently move it."""
    from .fullness import _check_line

    if len(pieces) == 1:
        return pieces[0]
    for piece in pieces:
        try:
            for edge in edges:
                _check_line(piece, edge, source)
        except BlockConstructionError:
            continue
        return piece
    raise BlockConstructionError(
        'DETAIL_PARTITION_PLACEMENT_CONFLICT',
        'Карман или накладная деталь выходит за контур, пересекает вытачку либо шов '
        'членения. Разместите её целиком на одной итоговой детали. Крепление кармана '
        'поперёк шва членения пока не поддерживается.',
        f'/garment_spec/design_intent/elements/{source}',
    )
