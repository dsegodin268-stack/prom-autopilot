import math
def tiered_markup(cost):
    if cost<=0: return 0
    if cost<3000: r=cost*1.50
    elif cost<5000: r=cost*1.45
    elif cost<10000: r=cost*1.30
    elif cost<30000: r=cost*1.20
    else: r=cost*1.10
    return math.ceil(r)
def price_item(cost, category=None, markup_cfg=None, competitor=None):
    std=tiered_markup(cost)
    if competitor and competitor>0 and competitor<std:
        floor=math.ceil(cost*((markup_cfg or {}).get("floor",1.15)))
        target=math.floor(competitor*0.99)
        price=target if target>=floor else std
    else:
        price=std
    return price, (round(price/cost,3) if cost else 0)
def margin_after_commission(price, cost, commission):
    if price<=0: return 0.0
    return round((price*(1-commission)-cost)/price,3)
