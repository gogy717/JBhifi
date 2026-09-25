INSERT INTO category (name) VALUES
    ('Laptops'), ('Headphones'), ('TVs');

INSERT INTO product (name, price, stock, category_id) VALUES
    ('MacBook Air M3',   1799.00, 12, 1),
    ('Sony WH-1000XM5',   549.95, 40, 1),   -- 注意这里 category_id 写错了，应该是 2
    ('LG OLED C4 65"',   3295.00,  5, 3);

INSERT INTO customer (email, name) VALUES
    ('a@uni.sydney.edu.au', 'Alice'),
    ('b@uni.sydney.edu.au', 'Bob');