"""Court listing and creation."""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Court

bp = Blueprint("courts", __name__, url_prefix="/courts")


@bp.route("")
@login_required
def index():
    courts = Court.query.all()
    return render_template("courts.html", courts=courts)


@bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        address = request.form.get("address", "").strip()
        lat = request.form.get("lat")
        lng = request.form.get("lng")

        if not all([name, address, lat, lng]):
            flash("All fields are required.")
            return render_template("create_court.html")

        try:
            lat = float(lat)
            lng = float(lng)
        except ValueError:
            flash("Invalid coordinates.")
            return render_template("create_court.html")

        court = Court(
            name=name,
            address=address,
            lat=lat,
            lng=lng,
            created_by=current_user.id,
        )
        db.session.add(court)
        db.session.commit()
        flash("Court created successfully!")
        return redirect(url_for("courts.index"))

    return render_template("create_court.html")
