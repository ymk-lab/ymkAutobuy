# Sleeve Notional defaults to min(cap, equity); buying power is an opt-in

The book must not silently scale with account fatness or Futu purchasing power. Sleeve Notional is the lesser of the operator cap and account equity. A confirmed Buying-Power Cap may replace equity in that min() so a margin-enabled Futu account can deploy more than equity; that choice is Next-Once and does not by itself place a margin order type. The older No Leverage rule remains the default sizing rule, not a claim about the broker account settings.
