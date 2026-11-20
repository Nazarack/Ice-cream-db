
import sqlite3
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = "sweetstock-development-key"

DATABASE = Path(__file__).parent / "database" / "inventory_new.db"
DATABASE.parent.mkdir(parents=True, exist_ok=True)

print("SweetStock database:", DATABASE.resolve())


# DATABASE CONNECTION
def get_db_connection():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


# INITIALIZE DATABASE

def check_products_table():
    connection = get_db_connection()

    columns = connection.execute(
        "PRAGMA table_info(products)"
    ).fetchall()

    print("\nPRODUCTS TABLE STRUCTURE:")
    for column in columns:
        print(dict(column))

    connection.close()

def initialize_database():
    connection = get_db_connection()

    connection.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            category TEXT NOT NULL
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            production_date TEXT NOT NULL,
            estimated_expiry TEXT,
            quantity_produced INTEGER NOT NULL,
            current_quantity INTEGER NOT NULL,
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    """)

    connection.commit()
    connection.close()


# DASHBOARD
@app.route("/")
def home():
    connection = get_db_connection()

    # Dashboard statistics
    total_products = connection.execute("""
        SELECT COUNT(*) FROM products
    """).fetchone()[0]

    total_stock = connection.execute("""
        SELECT COALESCE(SUM(current_quantity), 0)
        FROM batches
    """).fetchone()[0]

    total_batches = connection.execute("""
        SELECT COUNT(*) FROM batches
    """).fetchone()[0]

    # Recent production batches
    recent_batches = connection.execute("""
        SELECT
            batches.*,
            products.name AS product_name
        FROM batches
        JOIN products ON batches.product_id = products.id
        ORDER BY batches.production_date DESC, batches.id DESC
        LIMIT 5
    """).fetchall()

    connection.close()

    return render_template(
        "index.html",
        total_products=total_products,
        total_stock=total_stock,
        total_batches=total_batches,
        recent_batches=recent_batches
    )

# INVENTORY PAGE
@app.route("/inventory")
def inventory():
    connection = get_db_connection()

    search_term = request.args.get("search", "").strip()
    selected_category = request.args.get("category", "").strip()

    conditions = []
    parameters = []

    if search_term:
        conditions.append("p.name LIKE ?")
        parameters.append(f"%{search_term}%")

    if selected_category:
        conditions.append("p.category = ?")
        parameters.append(selected_category)

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    products = connection.execute(f"""
        SELECT
            p.id,
            p.name,
            p.category,
            COALESCE(SUM(b.current_quantity), 0) AS total_quantity
        FROM products p
        LEFT JOIN batches b ON p.id = b.product_id
        {where_clause}
        GROUP BY p.id
        ORDER BY p.name COLLATE NOCASE
    """, parameters).fetchall()

    categories = connection.execute("""
        SELECT DISTINCT category
        FROM products
        ORDER BY category COLLATE NOCASE
    """).fetchall()

    connection.close()

    return render_template(
        "inventory.html",
        products=products,
        categories=categories,
        search_term=search_term,
        selected_category=selected_category
    )
# PRODUCTION PAGE
@app.route("/production")
def production():
    connection = get_db_connection()

    products = connection.execute("""
        SELECT id, name, category
        FROM products
        ORDER BY name COLLATE NOCASE
    """).fetchall()

    batches = connection.execute("""
        SELECT
            batches.*,
            products.name AS product_name
        FROM batches
        JOIN products ON batches.product_id = products.id
        ORDER BY batches.production_date DESC
    """).fetchall()

    connection.close()

    return render_template(
        "production.html",
        products=products,
        batches=batches
    )


# ADD A NEW PRODUCT
@app.route("/products/add", methods=["POST"])
def add_product():
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip()

    if not name or not category:
        flash("Please enter a product name and category.")
        return redirect(url_for("manage_products"))

    connection = get_db_connection()

    try:
        connection.execute("""
            INSERT INTO products (name, category)
            VALUES (?, ?)
        """, (name, category))

        connection.commit()
        flash("Product added successfully!")

    except sqlite3.IntegrityError as error:
        connection.rollback()

        if "UNIQUE constraint failed" in str(error):
            flash("A product with this name already exists.")
        else:
            flash(f"Database error: {error}")

    except sqlite3.Error as error:
        connection.rollback()
        flash(f"Database error: {error}")

    finally:
        connection.close()

    return redirect(url_for("manage_products"))

# ADD A PRODUCTION BATCH
# Choose an existing product OR create a new product
@app.route("/batches/add", methods=["POST"])
def add_batch():
    product_id = request.form.get("product_id", "").strip()
    new_name = request.form.get("new_product_name", "").strip()
    new_category = request.form.get("new_product_category", "").strip()
    production_date = request.form.get("production_date", "")
    estimated_expiry = request.form.get("estimated_expiry", "")

    try:
        quantity = int(request.form.get("quantity", ""))

        if not production_date or quantity <= 0:
            raise ValueError

    except ValueError:
        flash("Please enter a valid production date and quantity.")
        return redirect(url_for("home"))

    connection = get_db_connection()

    try:
        if product_id:
            selected_product = connection.execute(
                "SELECT id FROM products WHERE id = ?",
                (product_id,)
            ).fetchone()

            if selected_product is None:
                raise ValueError("Selected product was not found.")

            final_product_id = selected_product["id"]

        elif new_name and new_category:
            existing_product = connection.execute(
                "SELECT id FROM products WHERE name = ?",
                (new_name,)
            ).fetchone()

            if existing_product:
                final_product_id = existing_product["id"]
                flash("Existing product recognised. Adding a batch to it.")

            else:
                cursor = connection.execute("""
                    INSERT INTO products (name, category)
                    VALUES (?, ?)
                """, (new_name, new_category))

                final_product_id = cursor.lastrowid

        else:
            raise ValueError(
                "Please select an existing product or enter a new product."
            )

        connection.execute("""
            INSERT INTO batches (
                product_id,
                production_date,
                estimated_expiry,
                quantity_produced,
                current_quantity
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            final_product_id,
            production_date,
            estimated_expiry or None,
            quantity,
            quantity
        ))

        connection.commit()
        flash("Production batch added successfully!")

    except (sqlite3.IntegrityError, ValueError) as error:
        connection.rollback()
        flash(str(error))

    finally:
        connection.close()

    return redirect(url_for("home"))


# UPDATE AVAILABLE STOCK
@app.route("/batches/update/<int:batch_id>", methods=["POST"])
def update_batch(batch_id):
    try:
        new_quantity = int(request.form.get("current_quantity", ""))

        if new_quantity < 0:
            raise ValueError

    except ValueError:
        flash("Please enter a valid quantity.")
        return redirect(url_for("home"))

    connection = get_db_connection()

    batch = connection.execute(
        "SELECT * FROM batches WHERE id = ?",
        (batch_id,)
    ).fetchone()

    if batch is None:
        flash("Batch not found.")

    elif new_quantity > batch["quantity_produced"]:
        flash("Available quantity cannot exceed the original production quantity.")

    else:
        connection.execute(
            "UPDATE batches SET current_quantity = ? WHERE id = ?",
            (new_quantity, batch_id)
        )
        connection.commit()
        flash("Stock updated successfully!")

    connection.close()

    return redirect(url_for("home"))


# MANAGE PRODUCTS PAGE
# MANAGE PRODUCTS PAGE
@app.route("/products/manage")
def manage_products():
    connection = get_db_connection()

    product_rows = connection.execute("""
        SELECT id, name, category
        FROM products
        ORDER BY name COLLATE NOCASE
    """).fetchall()

    products = []

    for product in product_rows:
        product_data = dict(product)

        batches = connection.execute("""
            SELECT
                id,
                production_date,
                estimated_expiry,
                quantity_produced,
                current_quantity
            FROM batches
            WHERE product_id = ?
            ORDER BY production_date DESC, id DESC
        """, (product["id"],)).fetchall()

        product_data["batches"] = [
            dict(batch) for batch in batches
        ]

        product_data["total_quantity"] = sum(
            batch["current_quantity"] for batch in batches
        )

        product_data["batch_count"] = len(batches)

        products.append(product_data)

    connection.close()

    return render_template(
        "products.html",
        products=products
    )


# EDIT A PRODUCT
@app.route("/products/edit/<int:product_id>", methods=["POST"])
def edit_product(product_id):
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip()

    if not name or not category:
        flash("Please enter a valid name and category.")
        return redirect(url_for("manage_products"))

    connection = get_db_connection()

    try:
        cursor = connection.execute("""
            UPDATE products
            SET name = ?, category = ?
            WHERE id = ?
        """, (name, category, product_id))

        connection.commit()

        if cursor.rowcount == 0:
            flash("Product not found.")
        else:
            flash("Product updated successfully!")

    except sqlite3.IntegrityError:
        connection.rollback()
        flash("Another product already has that name.")

    finally:
        connection.close()

    return redirect(url_for("manage_products"))


# DELETE A PRODUCT AND ITS BATCHES
@app.route("/products/delete/<int:product_id>", methods=["POST"])
def delete_product(product_id):
    connection = get_db_connection()

    product = connection.execute(
        "SELECT id FROM products WHERE id = ?",
        (product_id,)
    ).fetchone()

    if product is None:
        flash("Product not found.")

    else:
        connection.execute(
            "DELETE FROM batches WHERE product_id = ?",
            (product_id,)
        )

        connection.execute(
            "DELETE FROM products WHERE id = ?",
            (product_id,)
        )

        connection.commit()
        flash("Product and its production batches deleted.")

    connection.close()

    return redirect(url_for("manage_products"))


# TEMPORARY DATABASE CHECK
@app.route("/debug-products")
def debug_products():
    connection = get_db_connection()

    products = connection.execute("""
        SELECT id, name, category
        FROM products
        ORDER BY name
    """).fetchall()

    connection.close()

    return "<br>".join(
        f"ID: {p['id']} | Name: {p['name']} | Category: {p['category']}"
        for p in products
    ) or "No products found."


# START APPLICATION

if __name__ == "__main__":
    app.run(debug=True)