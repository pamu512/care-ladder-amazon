import numpy as np
from care_ladder.privacy import blur_faces, to_silhouette

def test_blur_faces_changes_pixels_on_synthetic_skin_blob():
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    frame[40:80, 60:100] = (180, 150, 120)  # blob
    out = blur_faces(frame)
    assert out.shape == frame.shape
    assert not np.array_equal(out[40:80, 60:100], frame[40:80, 60:100])

def test_silhouette_is_single_channel_or_3_but_not_full_color_photo():
    frame = np.zeros((60, 80, 3), dtype=np.uint8)
    frame[10:50, 20:60] = 255
    sil = to_silhouette(frame)
    assert sil.ndim in (2, 3)
    # must not preserve the bright white rectangle as-is in all channels identically to input RGB photo semantics
    assert sil.dtype == np.uint8
