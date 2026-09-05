from __future__ import annotations

import dba_component_market_v19 as v


def main() -> None:
    existed=v.core.RETAIL_SNAPSHOT.exists()
    saved=v.core.RETAIL_SNAPSHOT.read_bytes() if existed else None
    if existed:
        v.core.RETAIL_SNAPSHOT.unlink()
    try:
        dummy={'components':[],'component_alternatives':{}}

        mb=v.choose('MOTHERBOARD',dummy)
        assert mb['winner']['sku']=='ASROCK_B850M_PRO_A_WIFI',mb
        assert mb['runner_up'] is not None
        cheap_fail=next(x for x in mb['evaluated'] if x.get('sku')=='GIGABYTE_B650M_GAMING_WIFI6E')
        assert cheap_fail['eligible'] is False and '<4 DIMM' in cheap_fail['hard_gate_failures'],cheap_fail
        old_gigabyte=next(x for x in mb['evaluated'] if x.get('sku')=='GIGABYTE_B650M_GAMING_PLUS_WIFI')
        assert old_gigabyte['dominated'] is True and old_gigabyte['dominated_by'],old_gigabyte
        assert not any('B850 chipset' in s for x in mb['evaluated'] for s in (x.get('advantages') or []))

        # Formula regression intentionally does NOT force the live PSU winner. With
        # bootstrap prices A750GL can win; after the retail snapshot the same formula
        # must recompute from the verified prices.
        psu=v.choose('PSU',dummy)
        frontier=[x for x in psu['evaluated'] if x.get('eligible') and not x.get('dominated')]
        assert psu['winner'] and int(psu['winner']['effective_cost_dkk'])==min(int(x['effective_cost_dkk']) for x in frontier),psu
        assert any(x.get('sku')=='MSI_A750GL_PCIE5' for x in frontier)
        assert any(x.get('sku')=='MSI_A850GL_PCIE5_II' for x in frontier)

        cooler=v.choose('COOLER',dummy)
        assert cooler['winner']['sku']=='ARCTIC_FREEZER_36_BLACK',cooler
        storage=v.choose('STORAGE',dummy)
        assert storage['winner']['sku']=='WD_BLUE_SN580_1TB',storage

        print('PASS V19 MARKET FORMULA + PARETO REGRESSION')
    finally:
        if existed and saved is not None:
            v.core.RETAIL_SNAPSHOT.write_bytes(saved)


if __name__=='__main__':
    main()
