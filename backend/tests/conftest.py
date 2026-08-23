from exchange.testnet_gateway import TestnetCredentials

# `TestnetCredentials` is a production dataclass, not a pytest test class.
# Mark it explicitly so importing it into test modules does not create a
# PytestCollectionWarning merely because its name starts with "Test".
TestnetCredentials.__test__ = False
