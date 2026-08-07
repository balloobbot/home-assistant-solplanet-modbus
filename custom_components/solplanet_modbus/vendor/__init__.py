"""Vendored libraries for the Solplanet Ai-Logger (Modbus) integration.

``solplanet_modbus`` (the device library) is copied here verbatim from
https://github.com/balloobbot/solplanet-modbus until it is published to PyPI,
at which point this package goes away in favor of a ``manifest.json``
requirement. Its only dependency, ``modbus-connection``, *is* on PyPI and is
installed through the manifest. All of the library's internal imports are
relative, so it works unchanged as a sub-package.
"""
