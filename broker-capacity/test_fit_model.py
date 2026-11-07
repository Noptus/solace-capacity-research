import itertools
import unittest

from fit_model import nnls,solve,fit_roofline


class FitModel(unittest.TestCase):
    def test_full_rank_known_nonnegative_model(self):
        x=[[1,s,f,s*f] for s,f in itertools.product([1,2,4],[1,3])]
        coef=[2,3,4,5]
        y=[sum(a*b for a,b in zip(row,coef)) for row in x]
        estimated,loss=nnls(x,y)
        self.assertLess(loss,1e-14)
        for a,b in zip(estimated,coef):self.assertAlmostEqual(a,b,places=8)

    def test_negative_unconstrained_solution_is_rejected(self):
        coef,loss=nnls([[1,0],[1,1],[1,2]],[3,2,1])
        self.assertAlmostEqual(coef[0],2)
        self.assertEqual(coef[1],0)
        self.assertAlmostEqual(loss,2)

    def test_collinear_features_do_not_break_fit(self):
        coef,loss=nnls([[1,1],[2,2],[3,3]],[2,4,6])
        self.assertLess(loss,1e-18)
        self.assertAlmostEqual(sum(coef),2)

    def test_singular_system_is_identified(self):
        self.assertIsNone(solve([[1,1],[1,1]],[2,2]))

    def test_roofline_recovers_two_limits(self):
        x=[1,2,4,8,16,32]
        a,b=fit_roofline(x,[max(10,2*s) for s in x])
        self.assertAlmostEqual(a,10)
        self.assertAlmostEqual(b,2)

    def test_roofline_all_constant_and_all_byte_limited(self):
        for y in [[10]*4,[2,4,8,16]]:
            x=[1,2,4,8]
            a,b=fit_roofline(x,y)
            self.assertLess(sum((max(a,b*s)-v)**2 for s,v in zip(x,y)),1e-15)


if __name__=="__main__":unittest.main()
