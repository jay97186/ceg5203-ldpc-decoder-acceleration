"""PyTorch LDPC NMS/BF backend. CUDA in app; CPU supported for parity tests."""
from time import perf_counter
import numpy as np
import torch


class TorchDecoder:
    def __init__(self, code, algorithm='nms', alpha=.75, device='cuda:0'):
        self.device = torch.device(device)
        if self.device.type == 'cuda' and not torch.cuda.is_available():
            raise RuntimeError('無法使用 CUDA：請確認 NVIDIA GPU、驅動程式與 CUDA 版 PyTorch。可改選 CPU；不會自動假裝使用 GPU。')
        self.algorithm, self.alpha = algorithm, alpha
        self.checks = torch.as_tensor(code['checks'], dtype=torch.long, device=self.device)
        self.variables = torch.as_tensor(code['variables'], dtype=torch.long, device=self.device)
        self.edges = torch.as_tensor(code['variable_edges'], dtype=torch.long, device=self.device)
        self.n = code['H'].shape[1]
        self.lanes = torch.arange(self.checks.shape[1], device=self.device)[None, None, :]

    def sync(self):
        if self.device.type == 'cuda': torch.cuda.synchronize(self.device)

    @torch.inference_mode()
    def initialize(self, received, llrs):
        self.llr = torch.as_tensor(np.ascontiguousarray(llrs), dtype=torch.float32, device=self.device)
        self.words = (self.llr < 0).to(torch.uint8) if self.algorithm == 'nms' else torch.as_tensor(
            np.ascontiguousarray(received), dtype=torch.uint8, device=self.device)
        self.q = self.llr[:, self.checks].clone() if self.algorithm == 'nms' else None

    @torch.inference_mode()
    def syndrome(self):
        s = torch.zeros((self.words.shape[0], self.checks.shape[0]), dtype=torch.uint8, device=self.device)
        for lane in range(self.checks.shape[1]): s.bitwise_xor_(self.words[:, self.checks[:, lane]])
        return s

    @torch.inference_mode()
    def step(self):
        syndrome = self.syndrome()
        if self.algorithm == 'bf':
            counts = torch.zeros_like(self.words)
            for lane in range(self.variables.shape[1]): counts.add_(syndrome[:, self.variables[:, lane]])
            self.words = torch.bitwise_xor(self.words, (2*counts > self.variables.shape[1]).to(torch.uint8))
            return
        active = torch.any(syndrome != 0, dim=1)
        magnitude = self.q.abs()
        min_index = magnitude.argmin(dim=2)
        minima = torch.topk(magnitude, 2, dim=2, largest=False, sorted=True).values
        outgoing_magnitude = torch.where(self.lanes == min_index[:, :, None],
                                          minima[:, :, 1, None], minima[:, :, 0, None])
        negative = self.q < 0
        negative_parity = (negative.sum(dim=2) % 2).bool()[:, :, None]
        outgoing_negative = torch.logical_xor(negative_parity, negative)
        r = self.alpha*outgoing_magnitude*torch.where(outgoing_negative, -1., 1.)
        # Explicit additions match NumPy's degree-3 reduction order more closely.
        incoming = r.reshape(len(self.words), -1)[:, self.edges]
        total = incoming[:, :, 0].clone()
        for lane in range(1, self.edges.shape[1]): total = total + incoming[:, :, lane]
        posterior = self.llr + total
        new_q = (posterior[:, self.checks]-r).clamp(-30., 30.)
        self.words = torch.where(active[:, None], (posterior < 0).to(torch.uint8), self.words)
        self.q = torch.where(active[:, None, None], new_q, self.q)

    def host_words(self):
        return self.words.detach().cpu().numpy().copy()

    def warmup(self, batch_size=32, iterations=3):
        rng = np.random.default_rng(7)
        llr = rng.normal(0, 3, (batch_size, self.n)).astype(np.float32)
        self.initialize((llr < 0).astype(np.uint8), llr)
        for _ in range(iterations): self.step()
        self.sync()

    def info(self):
        return dict(backend='pytorch', torch_version=torch.__version__, cuda_runtime=torch.version.cuda,
                    device=str(self.device), device_name=torch.cuda.get_device_name(self.device)
                    if self.device.type == 'cuda' else 'CPU (backend test only)')
