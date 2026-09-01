from __future__ import annotations

import acurast_valuation as legacy
from acurast_core_compat import core_compatibility as enhanced_core_compatibility

_LEGACY=legacy.core_compatibility


def _core(model:str,title:str='',description:str=''):
    return enhanced_core_compatibility(model,title,description,_LEGACY)


legacy.core_compatibility=_core

import acurast_valuation_fixed as fixed


if __name__=='__main__':
    fixed.main()
