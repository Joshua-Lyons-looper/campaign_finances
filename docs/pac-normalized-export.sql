-- Run from the repository root with psql -X -v ON_ERROR_STOP=1.
-- Export both period values: the official 2023/2024 partition permits both.
-- Keep all transaction types for reconciliation: amendments can change type.
\copy (SELECT sub_id::text AS normalized_sub_id, orig_sub_id::text AS original_sub_id, cmte_id, recipient_cmte_id, clean_recipient_cmte_id, cand_id, file_num::text AS file_num, tran_id, image_num, disb_tp, disb_amt, disb_dt, memo_cd, action_cd, action_cd_desc, link_id::text AS link_id, filing_form, rpt_yr, rpt_tp, two_year_transaction_period, pg_date FROM disclosure.fec_fitem_sched_b_2023_2024) TO 'data/schedule-b-2024.csv' WITH (FORMAT csv, HEADER true)
