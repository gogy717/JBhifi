DROP TABLE IF EXISTS order_item CASCADE;
DROP TABLE IF EXISTS "order"    CASCADE;
DROP TABLE IF EXISTS product    CASCADE;
DROP TABLE IF EXISTS category   CASCADE;
DROP TABLE IF EXISTS customer   CASCADE;

CREATE TABLE category (
    id   INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE product (
    id          INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        VARCHAR(200)  NOT NULL,
    price       NUMERIC(10,2) NOT NULL CHECK (price >= 0),
    stock       INT           NOT NULL DEFAULT 0 CHECK (stock >= 0),
    category_id INT REFERENCES category(id) ON DELETE SET NULL
);

CREATE TABLE customer (
    id      INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email   VARCHAR(255) NOT NULL UNIQUE,
    name    VARCHAR(200) NOT NULL,
    joined  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE "order" (
    id          INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id INT NOT NULL REFERENCES customer(id),
    placed_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE order_item (
    order_id   INT NOT NULL REFERENCES "order"(id) ON DELETE CASCADE,
    product_id INT NOT NULL REFERENCES product(id),
    quantity   INT NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(10,2) NOT NULL,   -- 下单时的价格，不能靠 join product
    PRIMARY KEY (order_id, product_id)
);