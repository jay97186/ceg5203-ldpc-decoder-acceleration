"""Explicit YOLO CPU/CUDA selection; never silently fall back."""

def normalize_device(value):
    value = str(value).strip().lower()
    if value in ('cpu', 'cpu (pytorch)'): return 'cpu'
    if value in ('gpu', 'gpu (cuda)', 'cuda', 'cuda:0', '0'): return '0'
    raise ValueError('請選 CPU 或 GPU (CUDA)；命令列使用 --device cpu 或 --device cuda。')


def ensure_device(value):
    import torch
    device = normalize_device(value)
    if device != 'cpu':
        if not torch.cuda.is_available():
            raise ValueError(f'CUDA GPU 不可用（PyTorch {torch.__version__}，CUDA runtime={torch.version.cuda}）。請檢查 NVIDIA GPU/驅動或改選 CPU；程式不會自動改跑CPU。')
        # Actual allocation/operation catches inaccessible devices or unsupported arch.
        probe = torch.ones(1, device='cuda:0') + 1
        torch.cuda.synchronize(0)
        del probe
    return device


def device_description(value):
    import torch
    return 'CPU (PyTorch)' if value == 'cpu' else f'GPU CUDA: {torch.cuda.get_device_name(0)}'
