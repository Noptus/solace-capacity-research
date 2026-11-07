from collections import Counter
from fractions import Fraction as F
import itertools
import random
import unittest

from dependence import bounds,marginal


def hist(values):
    return [{"value":x,"weight":n} for x,n in Counter(values).items()]


class DependenceBounds(unittest.TestCase):
    def test_broker_counterexample(self):
        result=bounds(hist([1,9]),hist([1,9]))
        self.assertEqual(result["lower_product_expectation_exact"],"9")
        self.assertEqual(result["upper_product_expectation_exact"],"41")
        self.assertEqual(result["independence_product_expectation_exact"],"25")

    def test_finance_sign_change(self):
        result=bounds(hist([F(1,2),F(2)]),hist([F(1,4),F(9,10)]),F(3,5))
        self.assertEqual(F(result["net_lower_exact"]),F(-1,8))
        self.assertEqual(F(result["net_upper_exact"]),F(29,80))
        self.assertEqual(F(result["net_independence_exact"]),F(19,160))

    def test_unequal_discrete_weights_and_witness_marginals(self):
        left=[{"value":1,"weight":1},{"value":10,"weight":3}]
        right=[{"value":2,"weight":2},{"value":5,"weight":1}]
        result=bounds(left,right)
        for key in ["minimizing_joint_distribution","maximizing_joint_distribution"]:
            xs,ys=Counter(),Counter()
            for atom in result[key]:
                xs[F(atom["x"])]+=F(atom["probability"])
                ys[F(atom["y"])]+=F(atom["probability"])
            self.assertEqual(dict(xs),dict(marginal(left)))
            self.assertEqual(dict(ys),dict(marginal(right)))

    def test_exhaustive_permutation_oracle(self):
        rng=random.Random(1007)
        for _ in range(80):
            n=rng.randrange(1,7)
            x=[rng.randrange(10) for _ in range(n)]
            y=[rng.randrange(10) for _ in range(n)]
            possible=[sum(F(a*b,n) for a,b in zip(x,yp)) for yp in set(itertools.permutations(y))]
            result=bounds(hist(x),hist(y))
            self.assertEqual(F(result["lower_product_expectation_exact"]),min(possible))
            self.assertEqual(F(result["upper_product_expectation_exact"]),max(possible))

    def test_independence_is_inside_the_sharp_interval(self):
        rng=random.Random(1008)
        for _ in range(500):
            x=[rng.randrange(100) for _ in range(rng.randrange(1,12))]
            y=[rng.randrange(100) for _ in range(rng.randrange(1,12))]
            r=bounds(hist(x),hist(y))
            self.assertLessEqual(F(r["lower_product_expectation_exact"]),F(r["independence_product_expectation_exact"]))
            self.assertLessEqual(F(r["independence_product_expectation_exact"]),F(r["upper_product_expectation_exact"]))

    def test_zero_mass_duplicate_values_and_scaling(self):
        result=bounds([{"value":3,"weight":0},{"value":2,"weight":2},{"value":2,"weight":3}],hist([7]))
        self.assertEqual(result["lower_product_expectation_exact"],"14")
        self.assertEqual(result["upper_product_expectation_exact"],"14")

    def test_invalid_inputs(self):
        for bad in [[],[{"value":1,"weight":0}],[{"value":True,"weight":1}],
                    [{"value":-1,"weight":1}],[{"value":1,"weight":"NaN"}]]:
            with self.assertRaises(ValueError):marginal(bad)


if __name__=="__main__":unittest.main()
