-- Domains: reusable column types that carry their own CHECK, so a rule is written once
-- and every column of that type obeys it (domain integrity).

-- BR02: money is non-negative with exactly two decimals (never float).
CREATE DOMAIN money_aud AS NUMERIC(10,2)
    CONSTRAINT br02_money_nonneg CHECK (VALUE >= 0);

-- BR01: well-formed and stored in lower case, so UNIQUE(email) is effectively case-insensitive.
CREATE DOMAIN email_address AS TEXT
    CONSTRAINT br01_email_format CHECK (VALUE ~ '^[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$');

CREATE DOMAIN au_state AS TEXT
    CONSTRAINT au_state_valid CHECK (VALUE IN ('NSW', 'VIC', 'QLD', 'WA', 'SA', 'TAS', 'ACT', 'NT'));

CREATE DOMAIN au_postcode AS TEXT
    CONSTRAINT au_postcode_format CHECK (VALUE ~ '^[0-9]{4}$');

CREATE DOMAIN fulfilment AS TEXT
    CONSTRAINT fulfilment_valid CHECK (VALUE IN ('delivery', 'click_collect'));

-- Shared by customer_order.status and the transition/history tables, so the three can't drift apart.
CREATE DOMAIN order_status AS TEXT
    CONSTRAINT order_status_valid CHECK (VALUE IN
        ('placed', 'paid', 'picking', 'shipped', 'delivered', 'ready', 'collected', 'cancelled'));
