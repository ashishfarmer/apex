import unittest

import apex
import torch


class TestFusedAdagrad(unittest.TestCase):
    def setUp(self, max_abs_diff=1e-6, max_rel_diff=1, iters=7):
        self.max_abs_diff = max_abs_diff
        self.max_rel_diff = max_rel_diff
        self.iters = iters
        torch.cuda.manual_seed(9876)

    def tearDown(self):
        pass

    def gen_param_optim(self, tensors, adagrad_option, apex_only=False):
        ref_param = []
        tst_param = []
        for tensor in tensors:
            if apex_only:
                ref_param.append(torch.nn.Parameter(tensor.clone().float()))
            else:
                ref_param.append(torch.nn.Parameter(tensor.clone()))
            tst_param.append(torch.nn.Parameter(tensor.clone()))

        if apex_only:
            ref_optim = apex.optimizers.FusedAdagrad(ref_param, **adagrad_option)
        else:
            ref_optim = torch.optim.Adagrad(ref_param, **adagrad_option)
        tst_optim = apex.optimizers.FusedAdagrad(tst_param, **adagrad_option)

        return (ref_param, tst_param, ref_optim, tst_optim)

    def gen_grad(self, ref_param, tst_param, apex_only=False):
        for p_ref, p_tst in zip(ref_param, tst_param):
            p_tst.grad = torch.rand_like(p_tst)
            p_ref.grad = p_tst.grad.detach().float() if apex_only else p_tst.grad

    def gen_mixed_grad(self, ref_param, tst_param, scale=1.0):
        half_grads = []
        for p_ref, _ in zip(ref_param, tst_param):
            half_grads.append(torch.rand_like(p_ref).half())
            p_ref.grad = half_grads[-1].float() / scale
        return half_grads

    def get_max_diff(self, ref_param, tst_param, apex_only=False):
        max_abs_diff = max_rel_diff = 0
        for p_ref, p_tst in zip(ref_param, tst_param):
            if apex_only:
                p_tst = p_tst.float()
            max_abs_diff_p = (p_ref - p_tst).abs().max().item()
            max_rel_diff_p = ((p_ref - p_tst) / p_ref).abs().max().item()

            if max_abs_diff_p > max_abs_diff:
                max_abs_diff = max_abs_diff_p
            if max_rel_diff_p > max_rel_diff:
                max_rel_diff = max_rel_diff_p

        return max_abs_diff, max_rel_diff

    def gen_single_type_test(self, param_type=torch.float, apex_only=False):
        nelem = 278011
        adagrad_option = {"lr": 5e-4, "eps": 1e-08, "weight_decay": 1.0e-5}

        tensor = torch.rand(nelem, dtype=param_type, device="cuda")
        ref_param, tst_param, ref_optim, tst_optim = self.gen_param_optim(
            [tensor], adagrad_option, apex_only=apex_only
        )

        for _ in range(self.iters):
            self.gen_grad(ref_param, tst_param, apex_only=apex_only)
            ref_optim.step()
            tst_optim.step()
            max_abs_diff, max_rel_diff = self.get_max_diff(ref_param, tst_param, apex_only=apex_only)

            self.assertLessEqual(max_abs_diff, self.max_abs_diff)
            if not apex_only:
                self.assertLessEqual(max_rel_diff, self.max_rel_diff)

    def test_float(self):
        self.gen_single_type_test(param_type=torch.float)

    @unittest.skip("PyTorch optimizer is not numerically correct for fp16")
    def test_half(self):
        self.gen_single_type_test(param_type=torch.float16)

    # Compares bfloat16 computation against float32 as gold standard.
    # Uses apex optimizers(controlled by apex_only flag) for both types.
    # Doesn't use upstream optimizer like other tests as they seem to be
    # numerically unstable for half types(see skip note for test above).
    def test_bfloat16(self):
        self.max_abs_diff = 1e-2
        self.gen_single_type_test(param_type=torch.bfloat16, apex_only=True)

    def test_multi_params(self):
        sizes = [[4096, 1024], [4096], [4096, 2048], [32320, 1024], [1]]
        adagrad_option = {"lr": 5e-4, "eps": 1e-08, "weight_decay": 0}

        tensors = []
        for size in sizes:
            tensors.append(torch.rand(size, dtype=torch.float, device="cuda"))
        ref_param, tst_param, ref_optim, tst_optim = self.gen_param_optim(
            tensors, adagrad_option
        )

        for _ in range(self.iters):
            self.gen_grad(ref_param, tst_param)
            ref_optim.step()
            tst_optim.step()
            max_abs_diff, max_rel_diff = self.get_max_diff(ref_param, tst_param)
            self.assertLessEqual(max_abs_diff, self.max_abs_diff)
            self.assertLessEqual(max_rel_diff, self.max_rel_diff)

    def test_adagrad_option(self):
        nelem = 1
        adagrad_option = {"lr": 0.01, "eps": 3e-06, "weight_decay": 0}

        tensor = torch.rand(nelem, dtype=torch.float, device="cuda")
        ref_param, tst_param, ref_optim, tst_optim = self.gen_param_optim(
            [tensor], adagrad_option
        )

        for _ in range(self.iters):
            self.gen_grad(ref_param, tst_param)
            ref_optim.step()
            tst_optim.step()
            max_abs_diff, max_rel_diff = self.get_max_diff(ref_param, tst_param)

            self.assertLessEqual(max_abs_diff, self.max_abs_diff)
            self.assertLessEqual(max_rel_diff, self.max_rel_diff)
