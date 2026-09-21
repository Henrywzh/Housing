"""Shared definition of the regeneration submarkets, in both geographies we use.

Postcode sectors are what Land Registry transactions carry, so they drive the
price work. MSOAs are what the census, income and crime data are published on,
so they drive everything social. The two do not align exactly -- an MSOA is a
population-equalised statistical area, a postcode sector is a delivery
convenience -- so a submarket is defined separately in each and the overlap is
close but not identical. Every MSOA below is named by the House of Commons
Library naming project, so the names are official, not invented here.
"""

SUBMARKET_MSOA = {
    "Nine Elms / Battersea":       ["E02007083", "E02000923"],
    "Canary Wharf & Isle of Dogs": ["E02006854", "E02006853", "E02000894",
                                    "E02000893", "E02007114"],
    "North Greenwich":             ["E02006992", "E02006993"],
    "Canning Town / Royal Docks":  ["E02000740", "E02000743", "E02000744",
                                    "E02000747", "E02000749", "E02006999"],
    "Stratford":                   ["E02000722", "E02000725", "E02006996", "E02006995"],
    "Canada Water":                ["E02000813", "E02000814"],
    "Elephant & Castle":           ["E02000815"],
    "Wembley Park":                ["E02006955"],
    "North Acton":                 ["E02000252"],
    "White City":                  ["E02000373"],
}

MSOA_TO_SUBMARKET = {m: k for k, ms in SUBMARKET_MSOA.items() for m in ms}
