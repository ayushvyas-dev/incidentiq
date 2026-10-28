# DynamoDB ProvisionedThroughputExceededException

When user session lookup fails with ProvisionedThroughputExceededException, inspect partition key access distribution. Hot partitions overload single partition limits (1000 WCU / 3000 RCU). Add random suffix salting to partition keys or switch to DynamoDB On-Demand capacity mode.
