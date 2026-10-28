# ClickHouse Too Many Parts in All Parts in Table

When analytical event ingestion fails with DB::Exception: Too many parts in all data parts in table, verify write batch sizes. Frequent single-row INSERTs create hundreds of tiny parts faster than background merges can consolidate. Buffer writes and insert batches of at least 10,000 rows.
