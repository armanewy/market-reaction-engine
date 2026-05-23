# Biotech Catalyst Outlier Audit

This audit tries to break the Agent 3D result. It does not change parser labels, thresholds, or event definitions.

## Concentration Summary

- event rows: 97
- top 1 absolute h1 event share: 0.09654858870425914
- top 3 absolute h1 event share: 0.2234687954593378
- top 5 absolute h1 event share: 0.29259242070732283
- top ticker: XENE (0.13071537561116328)
- top indication: unknown (0.11388972447317625)
- CRL / halt / failure rows: 29
- CRL / halt / failure absolute h1 share: 0.39619758004027705
- CRL / halt / failure mean h1: -0.10327288375928939

## Top Absolute h1 Events

| rank | ticker | event_type | direction | h1 | h3 | abs_share | event_id |
| --- | --- | --- | --- | ---: | ---: | ---: | --- |
| 1 | RCKT | trial_halt | negative | -0.993192 | -0.890408 | 0.096549 | RCKT_8-K_2025-05-27_0001140361-25-020409 |
| 2 | XENE | phase_3_readout | mixed | 0.726375 | 0.750637 | 0.070611 | XENE_8-K_2021-10-04_0001564590-21-049880 |
| 3 | VIR | phase_2_readout | mixed | -0.579249 | -0.468803 | 0.056309 | VIR_8-K_2023-07-20_0001193125-23-190147 |
| 4 | PRTA | trial_discontinuation | negative | -0.365620 | -0.354278 | 0.035542 | PRTA_8-K_2025-05-23_0001193125-25-125881 |
| 5 | KYMR | phase_1_readout | mixed | 0.345453 | 0.310663 | 0.033582 | KYMR_8-K_2025-12-08_0001193125-25-310572 |
| 6 | RVMD | phase_3_readout | mixed | 0.326078 | 0.405869 | 0.031698 | RVMD_8-K_2026-04-13_0001193125-26-152039 |
| 7 | AUPH | trial_discontinuation | negative | -0.303699 | -0.368219 | 0.029523 | AUPH_8-K_2024-02-15_0001600620-24-000010 |
| 8 | OMER | fda_complete_response_letter | negative | -0.288832 | -0.174153 | 0.028078 | OMER_8-K_2021-10-18_0001558370-21-013245 |
| 9 | IOVA | fda_approval | positive | 0.281950 | 0.544400 | 0.027408 | IOVA_8-K_2024-02-20_0001104659-24-025082 |
| 10 | TGTX | phase_3_readout | positive | 0.270827 | 0.374784 | 0.026327 | TGTX_8-K_2020-05-05_0001558370-20-005097 |

## Excluding Top Absolute h1 Events

| excluded | rows | h1 mean | h1 median | h3 mean | h10 mean |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 97 | -0.019299232924941758 | -0.0128316401680062 | -0.014640958773784424 | -0.014461091101718773 |
| 1 | 96 | -0.009154513466643161 | -0.012742665285642999 | -0.005518383815364601 | -0.006249193263471811 |
| 3 | 94 | -0.010914468187111153 | -0.012742665285642999 | -0.008634027294365378 | -0.009889633925064267 |
| 5 | 92 | -0.010932529343160384 | -0.012742665285642999 | -0.008347645459825952 | -0.009465805324017848 |

## Ticker Concentration

| ticker | events | abs_h1_share | mean_h1 |
| --- | ---: | ---: | ---: |
| XENE | 11 | 0.130715 | 0.059609 |
| RCKT | 6 | 0.126330 | -0.216593 |
| PRTA | 3 | 0.057427 | -0.196917 |
| VIR | 1 | 0.056309 | -0.579249 |
| NVAX | 3 | 0.052520 | -0.023735 |
| TGTX | 3 | 0.049766 | 0.119068 |
| IOVA | 4 | 0.046317 | 0.116285 |
| KYMR | 3 | 0.044733 | 0.153389 |
| NTLA | 5 | 0.038410 | -0.004381 |
| SNDX | 4 | 0.037168 | -0.087528 |

## Therapeutic Area / Indication Concentration

| indication | events | abs_h1_share | mean_h1 |
| --- | ---: | ---: | ---: |
| unknown | 10 | 0.113890 | -0.040195 |
| 12 patients with danon disease | 1 | 0.096549 | -0.993192 |
| focal epilepsy all primary and secondary seizure reduction endpoints statistically significant across all dose groups | 1 | 0.070611 | 0.726375 |
| committed to the pursuit of novel therapies that have the potential to address some of the world s most serious infectious disease | 1 | 0.056309 | -0.579249 |
| alzheimer s disease | 2 | 0.038714 | -0.166498 |
| ad and those with comorbid asthma and allergic rhinitis | 1 | 0.033582 | 0.345453 |
| metastatic pancreatic ductal adenocarcinoma pdac who had been previously treated | 1 | 0.031698 | 0.326078 |
| hematopoietic stem cell transplant associated thrombotic microangiopathy | 1 | 0.028078 | -0.288832 |
| blindness due to leber congenital amaurosis 10 lca10 | 2 | 0.028064 | -0.144348 |
| adult patients with unresectable or metastatic melanoma previously treated with a pd 1 blocking antibody | 1 | 0.027408 | 0.281950 |

## Strategy Trade Concentration

- available: True
- trades: 50
- top 1 absolute net-return share: 0.11843982032604408
- top 5 absolute net-return share: 0.3871398450380203
