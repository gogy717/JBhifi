-- Reference data: stores, staff, catalogue, promotions, opening stock, and a few demo customers.
-- One transaction: store and staff reference each other, and BR04 is only checked at COMMIT.
-- Bulk customers and orders will come from the seed generator (20_seed_generated.sql, plan §7).
BEGIN;
-- Day arithmetic below (date_trunc, + n days) in the stores' time zone, so seeded promotions start and
-- end at local midnight even across the daylight-saving change. Only for this transaction.
SET LOCAL timezone = 'Australia/Sydney';

-- ---------------------------------------------------------------- stores and staff
-- Ids are pinned so each store's manager can be named before the staff rows exist.

INSERT INTO store (store_id, name, store_type, suburb, state, manager_id) VALUES
    ( 1, 'Sydney CBD',        'retail',    'Sydney',         'NSW',  1),
    ( 2, 'Bondi Junction',    'retail',    'Bondi Junction', 'NSW',  2),
    ( 3, 'Parramatta',        'retail',    'Parramatta',     'NSW',  3),
    ( 4, 'Chatswood',         'retail',    'Chatswood',      'NSW',  4),
    ( 5, 'Melbourne Central', 'retail',    'Melbourne',      'VIC',  5),
    ( 6, 'Chadstone',         'retail',    'Chadstone',      'VIC',  6),
    ( 7, 'Doncaster',         'retail',    'Doncaster',      'VIC',  7),
    ( 8, 'Highpoint',         'retail',    'Maribyrnong',    'VIC',  8),
    ( 9, 'Brisbane City',     'retail',    'Brisbane',       'QLD',  9),
    (10, 'Chermside',         'retail',    'Chermside',      'QLD', 10),
    (11, 'Carindale',         'retail',    'Carindale',      'QLD', 11),
    (12, 'Robina',            'retail',    'Robina',         'QLD', 12),
    (13, 'Eastern Creek DC',  'warehouse', 'Eastern Creek',  'NSW', 13);

INSERT INTO staff (staff_id, store_id, staff_type, full_name, email) VALUES
    -- store managers (staff n manages store n)
    ( 1,  1, 'store', 'Olivia Nguyen',     'olivia.nguyen@jbhifi.example'),
    ( 2,  2, 'store', 'James Wilson',      'james.wilson@jbhifi.example'),
    ( 3,  3, 'store', 'Priya Sharma',      'priya.sharma@jbhifi.example'),
    ( 4,  4, 'store', 'Daniel Kim',        'daniel.kim@jbhifi.example'),
    ( 5,  5, 'store', 'Sophie Brown',      'sophie.brown@jbhifi.example'),
    ( 6,  6, 'store', 'Lucas Rossi',       'lucas.rossi@jbhifi.example'),
    ( 7,  7, 'store', 'Mia Papadopoulos',  'mia.papadopoulos@jbhifi.example'),
    ( 8,  8, 'store', 'Noah Taylor',       'noah.taylor@jbhifi.example'),
    ( 9,  9, 'store', 'Chloe Martin',      'chloe.martin@jbhifi.example'),
    (10, 10, 'store', 'Jack Thompson',     'jack.thompson@jbhifi.example'),
    (11, 11, 'store', 'Grace Lee',         'grace.lee@jbhifi.example'),
    (12, 12, 'store', 'Liam O''Connor',    'liam.oconnor@jbhifi.example'),
    (13, 13, 'store', 'Hannah Walker',     'hannah.walker@jbhifi.example'),
    -- store staff
    (14,  1, 'store', 'Aiden Chen',        'aiden.chen@jbhifi.example'),
    (15,  1, 'store', 'Zara Ahmed',        'zara.ahmed@jbhifi.example'),
    (16,  2, 'store', 'Isla Robinson',     'isla.robinson@jbhifi.example'),
    (17,  2, 'store', 'Mateo Garcia',      'mateo.garcia@jbhifi.example'),
    (18,  3, 'store', 'Ravi Patel',        'ravi.patel@jbhifi.example'),
    (19,  3, 'store', 'Emily Tran',        'emily.tran@jbhifi.example'),
    (20,  4, 'store', 'Ruby White',        'ruby.white@jbhifi.example'),
    (21,  4, 'store', 'Oscar Park',        'oscar.park@jbhifi.example'),
    (22,  5, 'store', 'Leo Russo',         'leo.russo@jbhifi.example'),
    (23,  5, 'store', 'Amelia Scott',      'amelia.scott@jbhifi.example'),
    (24,  6, 'store', 'Harper Kelly',      'harper.kelly@jbhifi.example'),
    (25,  6, 'store', 'Arjun Singh',       'arjun.singh@jbhifi.example'),
    (26,  7, 'store', 'Mason Wright',      'mason.wright@jbhifi.example'),
    (27,  7, 'store', 'Ava Nikolaidis',    'ava.nikolaidis@jbhifi.example'),
    (28,  8, 'store', 'Charlotte Hall',    'charlotte.hall@jbhifi.example'),
    (29,  8, 'store', 'Hugo Tanaka',       'hugo.tanaka@jbhifi.example'),
    (30,  9, 'store', 'Lachlan Young',     'lachlan.young@jbhifi.example'),
    (31,  9, 'store', 'Ella Murphy',       'ella.murphy@jbhifi.example'),
    (32, 10, 'store', 'Sienna Clarke',     'sienna.clarke@jbhifi.example'),
    (33, 10, 'store', 'Kai Nakamura',      'kai.nakamura@jbhifi.example'),
    (34, 11, 'store', 'Thomas King',       'thomas.king@jbhifi.example'),
    (35, 11, 'store', 'Layla Hassan',      'layla.hassan@jbhifi.example'),
    (36, 12, 'store', 'Matilda Green',     'matilda.green@jbhifi.example'),
    (37, 12, 'store', 'Finn Edwards',      'finn.edwards@jbhifi.example'),
    (38, 13, 'store', 'Samuel Baker',      'samuel.baker@jbhifi.example'),
    (39, 13, 'store', 'Yuki Sato',         'yuki.sato@jbhifi.example'),
    -- support staff belong to no store (BR05)
    (40, NULL, 'support', 'Nora Fitzgerald', 'nora.fitzgerald@jbhifi.example'),
    (41, NULL, 'support', 'Omar Haddad',     'omar.haddad@jbhifi.example'),
    (42, NULL, 'support', 'Jasmine Wong',    'jasmine.wong@jbhifi.example');

-- Pinned ids don't advance the identity sequences; move them past the seed so the next INSERT
-- from the API doesn't collide with id 1.
SELECT setval(pg_get_serial_sequence('store', 'store_id'), (SELECT max(store_id) FROM store));
SELECT setval(pg_get_serial_sequence('staff', 'staff_id'), (SELECT max(staff_id) FROM staff));

-- ---------------------------------------------------------------- catalogue
-- From here on rows refer to each other by natural key (name, sku), not by id.

INSERT INTO category (name) VALUES
    ('Computers & Tablets'), ('Phones & Wearables'), ('TV & Home Theatre'), ('Audio'), ('Gaming');

INSERT INTO category (name, parent_id)
SELECT v.name, parent.category_id
FROM (VALUES
        ('Laptops',            'Computers & Tablets'),
        ('Tablets',            'Computers & Tablets'),
        ('Smartphones',        'Phones & Wearables'),
        ('Smartwatches',       'Phones & Wearables'),
        ('TVs',                'TV & Home Theatre'),
        ('Soundbars',          'TV & Home Theatre'),
        ('Headphones',         'Audio'),
        ('Speakers',           'Audio'),
        ('Consoles',           'Gaming'),
        ('Gaming Accessories', 'Gaming')
     ) AS v(name, parent_name)
JOIN category parent ON parent.name = v.parent_name;

INSERT INTO brand (name) VALUES
    ('Apple'), ('ASUS'), ('Bose'), ('Garmin'), ('Google'), ('Hisense'), ('HP'), ('JBL'),
    ('Lenovo'), ('LG'), ('Microsoft'), ('Nintendo'), ('Samsung'), ('Sonos'), ('Sony'), ('TCL');

INSERT INTO product (sku, name, brand_id, category_id, base_price)
SELECT v.sku, v.name, b.brand_id, c.category_id, v.base_price
FROM (VALUES
        ('APL-MBA13-M4-256',     'MacBook Air 13-inch M4 16GB/256GB',               'Apple',     'Laptops',            1699.00),
        ('APL-MBP14-M4P-512',    'MacBook Pro 14-inch M4 Pro 24GB/512GB',           'Apple',     'Laptops',            3499.00),
        ('LEN-IPS5-14-R7',       'IdeaPad Slim 5 14" Ryzen 7 16GB/512GB',           'Lenovo',    'Laptops',            1299.00),
        ('HP-PAV15-I5',          'Pavilion 15 Core i5 16GB/512GB',                  'HP',        'Laptops',            1099.00),
        ('ASUS-ZB14-OLED',       'Zenbook 14 OLED Core Ultra 7 16GB/1TB',           'ASUS',      'Laptops',            1799.00),
        ('MS-SL7-13-X',          'Surface Laptop 7 13.8" Snapdragon X 16GB/512GB',  'Microsoft', 'Laptops',            1999.00),
        ('APL-IPAD11-A16-128',   'iPad 11-inch (A16) Wi-Fi 128GB',                  'Apple',     'Tablets',             599.00),
        ('APL-IPADAIR11-M3-128', 'iPad Air 11-inch (M3) Wi-Fi 128GB',               'Apple',     'Tablets',             999.00),
        ('SAM-TABS10FE-128',     'Galaxy Tab S10 FE Wi-Fi 128GB',                   'Samsung',   'Tablets',             749.00),
        ('LEN-TABM11-128',       'Tab M11 Wi-Fi 128GB',                             'Lenovo',    'Tablets',             349.00),
        ('MS-SP11-X-256',        'Surface Pro 11th Edition Snapdragon X 16GB/256GB','Microsoft', 'Tablets',            1799.00),
        ('APL-IP17-256',         'iPhone 17 256GB',                                 'Apple',     'Smartphones',        1399.00),
        ('APL-IP17PRO-256',      'iPhone 17 Pro 256GB',                             'Apple',     'Smartphones',        1999.00),
        ('SAM-S25-256',          'Galaxy S25 256GB',                                'Samsung',   'Smartphones',        1449.00),
        ('SAM-A56-256',          'Galaxy A56 5G 256GB',                             'Samsung',   'Smartphones',         749.00),
        ('GGL-PIX10-128',        'Pixel 10 128GB',                                  'Google',    'Smartphones',        1349.00),
        ('GGL-PIX9A-128',        'Pixel 9a 128GB',                                  'Google',    'Smartphones',         849.00),
        ('APL-AWS11-42',         'Apple Watch Series 11 GPS 42mm',                  'Apple',     'Smartwatches',        649.00),
        ('SAM-GW8-44',           'Galaxy Watch8 44mm Bluetooth',                    'Samsung',   'Smartwatches',        599.00),
        ('GAR-FR265',            'Forerunner 265',                                  'Garmin',    'Smartwatches',        649.00),
        ('GAR-VENU3',            'Venu 3',                                          'Garmin',    'Smartwatches',        749.00),
        ('LG-OLED65C5',          '65" C5 4K OLED evo Smart TV',                     'LG',        'TVs',                3295.00),
        ('SAM-QA55QN90F',        '55" QN90F Neo QLED 4K Smart TV',                  'Samsung',   'TVs',                2295.00),
        ('SONY-K65XR70',         '65" BRAVIA 7 Mini LED 4K Google TV',              'Sony',      'TVs',                2999.00),
        ('HIS-65U7Q',            '65" U7Q Mini-LED 4K Smart TV',                    'Hisense',   'TVs',                1499.00),
        ('TCL-55C755',           '55" C755 QD-Mini LED 4K Google TV',               'TCL',       'TVs',                 999.00),
        ('LG-43UT8050',          '43" UT80 4K LED Smart TV',                        'LG',        'TVs',                 599.00),
        ('SONOS-ARCULTRA',       'Arc Ultra Dolby Atmos Soundbar',                  'Sonos',     'Soundbars',          1499.00),
        ('SONOS-BEAM2',          'Beam (Gen 2) Soundbar',                           'Sonos',     'Soundbars',           699.00),
        ('SAM-HWQ990F',          'HW-Q990F 11.1.4ch Soundbar',                      'Samsung',   'Soundbars',          1999.00),
        ('SONY-HTS2000',         'HT-S2000 3.1ch Dolby Atmos Soundbar',             'Sony',      'Soundbars',           799.00),
        ('SONY-WH1000XM5-B',     'WH-1000XM5 Noise Cancelling Headphones (Black)',  'Sony',      'Headphones',          549.95),
        ('SONY-WF1000XM5-B',     'WF-1000XM5 Noise Cancelling Earbuds (Black)',     'Sony',      'Headphones',          419.00),
        ('APL-APP3',             'AirPods Pro 3',                                   'Apple',     'Headphones',          429.00),
        ('APL-AP4',              'AirPods 4',                                       'Apple',     'Headphones',          219.00),
        ('BOSE-QCULTRA-HP',      'QuietComfort Ultra Headphones',                   'Bose',      'Headphones',          649.95),
        ('JBL-T770NC-B',         'Tune 770NC Wireless Headphones (Black)',          'JBL',       'Headphones',          179.95),
        ('JBL-FLIP7-B',          'Flip 7 Portable Bluetooth Speaker (Black)',       'JBL',       'Speakers',            199.95),
        ('JBL-CHARGE6-B',        'Charge 6 Portable Bluetooth Speaker (Black)',     'JBL',       'Speakers',            279.95),
        ('SONOS-ERA100-B',       'Era 100 Smart Speaker (Black)',                   'Sonos',     'Speakers',            399.00),
        ('BOSE-SLFLEX2',         'SoundLink Flex (2nd Gen) Bluetooth Speaker',      'Bose',      'Speakers',            249.95),
        ('SONY-PS5-SLIM-DISC',   'PlayStation 5 Console (Slim, Disc)',              'Sony',      'Consoles',            799.95),
        ('SONY-PS5-PRO',         'PlayStation 5 Pro Console',                       'Sony',      'Consoles',           1199.95),
        ('NIN-SWITCH2',          'Switch 2 Console',                                'Nintendo',  'Consoles',            699.95),
        ('MS-XSX-1TB',           'Xbox Series X 1TB Console',                       'Microsoft', 'Consoles',            799.00),
        ('SONY-DUALSENSE-W',     'DualSense Wireless Controller (White)',           'Sony',      'Gaming Accessories',  119.95),
        ('MS-XBOXCTRL-B',        'Xbox Wireless Controller (Carbon Black)',         'Microsoft', 'Gaming Accessories',   89.95),
        ('NIN-SW2-PROCTRL',      'Switch 2 Pro Controller',                         'Nintendo',  'Gaming Accessories',  119.95)
     ) AS v(sku, name, brand_name, category_name, base_price)
JOIN brand b    ON b.name = v.brand_name
JOIN category c ON c.name = v.category_name;

INSERT INTO product_spec (product_id, spec_name, spec_value)
SELECT p.product_id, v.spec_name, v.spec_value
FROM (VALUES
        ('APL-MBA13-M4-256',     'Screen size', '13.6 in'), ('APL-MBA13-M4-256',     'Processor', 'Apple M4'),            ('APL-MBA13-M4-256',  'Storage', '256GB SSD'),
        ('APL-MBP14-M4P-512',    'Screen size', '14.2 in'), ('APL-MBP14-M4P-512',    'Processor', 'Apple M4 Pro'),        ('APL-MBP14-M4P-512', 'Storage', '512GB SSD'),
        ('LEN-IPS5-14-R7',       'Screen size', '14 in'),   ('LEN-IPS5-14-R7',       'Processor', 'AMD Ryzen 7'),         ('LEN-IPS5-14-R7',    'Storage', '512GB SSD'),
        ('HP-PAV15-I5',          'Screen size', '15.6 in'), ('HP-PAV15-I5',          'Processor', 'Intel Core i5'),       ('HP-PAV15-I5',       'Storage', '512GB SSD'),
        ('ASUS-ZB14-OLED',       'Screen size', '14 in'),   ('ASUS-ZB14-OLED',       'Processor', 'Intel Core Ultra 7'),  ('ASUS-ZB14-OLED',    'Storage', '1TB SSD'),
        ('MS-SL7-13-X',          'Screen size', '13.8 in'), ('MS-SL7-13-X',          'Processor', 'Snapdragon X Plus'),   ('MS-SL7-13-X',       'Storage', '512GB SSD'),
        ('APL-IPAD11-A16-128',   'Screen size', '11 in'),   ('APL-IPAD11-A16-128',   'Storage', '128GB'),
        ('APL-IPADAIR11-M3-128', 'Screen size', '11 in'),   ('APL-IPADAIR11-M3-128', 'Storage', '128GB'),
        ('SAM-TABS10FE-128',     'Screen size', '10.9 in'), ('SAM-TABS10FE-128',     'Storage', '128GB'),
        ('LEN-TABM11-128',       'Screen size', '11 in'),   ('LEN-TABM11-128',       'Storage', '128GB'),
        ('MS-SP11-X-256',        'Screen size', '13 in'),   ('MS-SP11-X-256',        'Storage', '256GB'),
        ('APL-IP17-256',         'Screen size', '6.3 in'),  ('APL-IP17-256',         'Storage', '256GB'),
        ('APL-IP17PRO-256',      'Screen size', '6.3 in'),  ('APL-IP17PRO-256',      'Storage', '256GB'),
        ('SAM-S25-256',          'Screen size', '6.2 in'),  ('SAM-S25-256',          'Storage', '256GB'),
        ('SAM-A56-256',          'Screen size', '6.7 in'),  ('SAM-A56-256',          'Storage', '256GB'),
        ('GGL-PIX10-128',        'Screen size', '6.3 in'),  ('GGL-PIX10-128',        'Storage', '128GB'),
        ('GGL-PIX9A-128',        'Screen size', '6.3 in'),  ('GGL-PIX9A-128',        'Storage', '128GB'),
        ('APL-AWS11-42',         'Case size', '42 mm'),     ('APL-AWS11-42',         'Connectivity', 'GPS'),
        ('SAM-GW8-44',           'Case size', '44 mm'),     ('SAM-GW8-44',           'Connectivity', 'Bluetooth'),
        ('GAR-FR265',            'Case size', '46 mm'),     ('GAR-FR265',            'Connectivity', 'GPS'),
        ('GAR-VENU3',            'Case size', '45 mm'),     ('GAR-VENU3',            'Connectivity', 'GPS'),
        ('LG-OLED65C5',          'Screen size', '65 in'),   ('LG-OLED65C5',          'Panel', 'OLED'),           ('LG-OLED65C5',   'Resolution', '4K'),
        ('SAM-QA55QN90F',        'Screen size', '55 in'),   ('SAM-QA55QN90F',        'Panel', 'Neo QLED'),       ('SAM-QA55QN90F', 'Resolution', '4K'),
        ('SONY-K65XR70',         'Screen size', '65 in'),   ('SONY-K65XR70',         'Panel', 'Mini LED'),       ('SONY-K65XR70',  'Resolution', '4K'),
        ('HIS-65U7Q',            'Screen size', '65 in'),   ('HIS-65U7Q',            'Panel', 'Mini LED'),       ('HIS-65U7Q',     'Resolution', '4K'),
        ('TCL-55C755',           'Screen size', '55 in'),   ('TCL-55C755',           'Panel', 'QD-Mini LED'),    ('TCL-55C755',    'Resolution', '4K'),
        ('LG-43UT8050',          'Screen size', '43 in'),   ('LG-43UT8050',          'Panel', 'LED'),            ('LG-43UT8050',   'Resolution', '4K'),
        ('SONOS-ARCULTRA',       'Channels', '9.1.4'),      ('SONOS-ARCULTRA',       'Dolby Atmos', 'Yes'),
        ('SONOS-BEAM2',          'Channels', '5.0'),        ('SONOS-BEAM2',          'Dolby Atmos', 'Yes'),
        ('SAM-HWQ990F',          'Channels', '11.1.4'),     ('SAM-HWQ990F',          'Dolby Atmos', 'Yes'),
        ('SONY-HTS2000',         'Channels', '3.1'),        ('SONY-HTS2000',         'Dolby Atmos', 'Yes'),
        ('SONY-WH1000XM5-B',     'Type', 'Over-ear'),       ('SONY-WH1000XM5-B',     'Noise cancelling', 'Yes'), ('SONY-WH1000XM5-B', 'Battery life', '30 h'),
        ('SONY-WF1000XM5-B',     'Type', 'In-ear'),         ('SONY-WF1000XM5-B',     'Noise cancelling', 'Yes'), ('SONY-WF1000XM5-B', 'Battery life', '8 h'),
        ('APL-APP3',             'Type', 'In-ear'),         ('APL-APP3',             'Noise cancelling', 'Yes'), ('APL-APP3',         'Battery life', '8 h'),
        ('APL-AP4',              'Type', 'In-ear'),         ('APL-AP4',              'Noise cancelling', 'No'),  ('APL-AP4',          'Battery life', '5 h'),
        ('BOSE-QCULTRA-HP',      'Type', 'Over-ear'),       ('BOSE-QCULTRA-HP',      'Noise cancelling', 'Yes'), ('BOSE-QCULTRA-HP',  'Battery life', '24 h'),
        ('JBL-T770NC-B',         'Type', 'Over-ear'),       ('JBL-T770NC-B',         'Noise cancelling', 'Yes'), ('JBL-T770NC-B',     'Battery life', '70 h'),
        ('JBL-FLIP7-B',          'Battery life', '14 h'),   ('JBL-FLIP7-B',          'Water resistance', 'IP68'),
        ('JBL-CHARGE6-B',        'Battery life', '24 h'),   ('JBL-CHARGE6-B',        'Water resistance', 'IP68'),
        ('SONOS-ERA100-B',       'Power', 'Mains'),         ('SONOS-ERA100-B',       'Connectivity', 'Wi-Fi, Bluetooth'),
        ('BOSE-SLFLEX2',         'Battery life', '12 h'),   ('BOSE-SLFLEX2',         'Water resistance', 'IP67'),
        ('SONY-PS5-SLIM-DISC',   'Storage', '1TB'),         ('SONY-PS5-SLIM-DISC',   'Disc drive', 'Yes'),
        ('SONY-PS5-PRO',         'Storage', '2TB'),         ('SONY-PS5-PRO',         'Disc drive', 'No'),
        ('NIN-SWITCH2',          'Storage', '256GB'),       ('NIN-SWITCH2',          'Disc drive', 'No'),
        ('MS-XSX-1TB',           'Storage', '1TB'),         ('MS-XSX-1TB',           'Disc drive', 'Yes'),
        ('SONY-DUALSENSE-W',     'Platform', 'PlayStation 5'),     ('SONY-DUALSENSE-W', 'Connectivity', 'Bluetooth, USB-C'),
        ('MS-XBOXCTRL-B',        'Platform', 'Xbox, PC'),          ('MS-XBOXCTRL-B',    'Connectivity', 'Bluetooth, USB-C'),
        ('NIN-SW2-PROCTRL',      'Platform', 'Nintendo Switch 2'), ('NIN-SW2-PROCTRL',  'Connectivity', 'Bluetooth, USB-C')
     ) AS v(sku, spec_name, spec_value)
JOIN product p ON p.sku = v.sku;

-- Promotions relative to the build date, so a fresh database always has past, current and upcoming ones.
INSERT INTO promotion (product_id, sale_price, starts_at, ends_at)
SELECT p.product_id, v.sale_price,
       date_trunc('day', now()) + v.starts_in_days * interval '1 day',
       date_trunc('day', now()) + v.ends_in_days   * interval '1 day'
FROM (VALUES
        ('SONY-WH1000XM5-B',    449.00, -60, -30),    -- ended
        ('APL-MBA13-M4-256',   1499.00, -45, -15),    -- ended
        ('SONY-WH1000XM5-B',    399.00,  -7,  30),    -- current
        ('APL-AP4',             189.00,  -7,  30),
        ('SAM-S25-256',        1199.00,  -3,  25),
        ('HIS-65U7Q',          1199.00, -10,  20),
        ('JBL-FLIP7-B',         149.95,  -2,  12),
        ('SONY-PS5-SLIM-DISC',  699.95,  14,  28),    -- upcoming
        ('LG-OLED65C5',        2795.00,  14,  28)
     ) AS v(sku, sale_price, starts_in_days, ends_in_days)
JOIN product p ON p.sku = v.sku;

-- ---------------------------------------------------------------- opening stock
-- Every product is ranged at every location. Deterministic quantities: retail 0–18 (some zero and low
-- stock to demo with), the warehouse 40–99.
INSERT INTO inventory (store_id, product_id, quantity)
SELECT s.store_id, p.product_id,
       CASE WHEN s.store_type = 'warehouse' THEN 40 + (p.product_id * 7) % 60
            ELSE (s.store_id * 7 + p.product_id * 11) % 19
       END
FROM store s
CROSS JOIN product p;

-- ---------------------------------------------------------------- demo customers
-- The storefront's "signed in as" switcher (a stand-in for the plan's demo login) picks one of these.

INSERT INTO customer (email, full_name, phone) VALUES
    ('alice.morgan@example.com', 'Alice Morgan', '0412 345 678'),
    ('ben.okafor@example.com',   'Ben Okafor',   '0423 456 789'),
    ('mei.zhou@example.com',     'Mei Zhou',     '0434 567 890'),
    ('tom.fraser@example.com',   'Tom Fraser',   NULL);

INSERT INTO customer_address (customer_id, address_no, line1, suburb, state, postcode, is_active)
SELECT c.customer_id, v.address_no, v.line1, v.suburb, v.state, v.postcode, v.is_active
FROM (VALUES
        ('alice.morgan@example.com', 1, '12 Harris St',    'Pyrmont',        'NSW', '2009', TRUE),
        ('ben.okafor@example.com',   1, '4/88 Chapel St',  'Windsor',        'VIC', '3181', FALSE),  -- moved out: kept, never edited (BR16)
        ('ben.okafor@example.com',   2, '27 Brunswick St', 'Fitzroy',        'VIC', '3065', TRUE),
        ('mei.zhou@example.com',     1, '9 Grey St',       'South Brisbane', 'QLD', '4101', TRUE),
        ('tom.fraser@example.com',   1, '150 Church St',   'Parramatta',     'NSW', '2150', TRUE)
     ) AS v(email, address_no, line1, suburb, state, postcode, is_active)
JOIN customer c ON c.email = v.email;

COMMIT;
