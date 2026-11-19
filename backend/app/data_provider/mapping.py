# Codici borsa di Yahoo → (codice MIC per exchange_calendars, mercato, etichetta)
YAHOO_EXCHANGES = {
    "MIL": ("XMIL", "ITA", "Borsa Italiana"),
    "GER": ("XETR", "EUR", "Xetra"),
    "FRA": ("XFRA", "EUR", "Francoforte"),
    "PAR": ("XPAR", "EUR", "Euronext Parigi"),
    "AMS": ("XAMS", "EUR", "Euronext Amsterdam"),
    "BRU": ("XBRU", "EUR", "Euronext Bruxelles"),
    "LIS": ("XLIS", "EUR", "Euronext Lisbona"),
    "MCE": ("XMAD", "EUR", "Madrid"),
    "VIE": ("XWBO", "EUR", "Vienna"),
    "HEL": ("XHEL", "EUR", "Helsinki"),
    "ISE": ("XDUB", "EUR", "Dublino"),
    "STO": ("XSTO", "EUR", "Stoccolma"),
    "CPH": ("XCSE", "EUR", "Copenaghen"),
    "OSL": ("XOSL", "EUR", "Oslo"),
    "EBS": ("XSWX", "EUR", "SIX Zurigo"),
    "LSE": ("XLON", "EUR", "Londra"),
    "NYQ": ("XNYS", "USA", "NYSE"),
    "NMS": ("XNYS", "USA", "Nasdaq"),
    "NGM": ("XNYS", "USA", "Nasdaq"),
    "NCM": ("XNYS", "USA", "Nasdaq"),
    "NAS": ("XNYS", "USA", "Nasdaq"),
    "ASE": ("XNYS", "USA", "NYSE American"),
    "PCX": ("XNYS", "USA", "NYSE Arca"),
    "BTS": ("XNYS", "USA", "Cboe BZX"),
}

# Valute quotate in centesimi da Yahoo → (valuta principale, divisore)
MINOR_CURRENCIES = {"GBp": ("GBP", 100), "GBX": ("GBP", 100), "ZAc": ("ZAR", 100), "ILA": ("ILS", 100)}

COUNTRIES = {
    "Italy": "IT", "United States": "US", "Germany": "DE", "France": "FR", "Netherlands": "NL",
    "Spain": "ES", "Belgium": "BE", "Portugal": "PT", "Austria": "AT", "Finland": "FI",
    "Ireland": "IE", "Luxembourg": "LU", "Switzerland": "CH", "United Kingdom": "GB",
    "Sweden": "SE", "Denmark": "DK", "Norway": "NO", "Greece": "GR", "Canada": "CA",
    "Japan": "JP", "China": "CN", "Hong Kong": "HK", "Taiwan": "TW", "South Korea": "KR",
    "Israel": "IL", "Australia": "AU", "Brazil": "BR", "Mexico": "MX", "India": "IN",
    "Bermuda": "BM", "Cayman Islands": "KY", "Jersey": "JE", "Guernsey": "GG", "Uruguay": "UY",
    "Argentina": "AR", "Singapore": "SG", "South Africa": "ZA", "Poland": "PL", "Czech Republic": "CZ",
}

YAHOO_TYPES = {"EQUITY": "stock", "ETF": "etf"}
