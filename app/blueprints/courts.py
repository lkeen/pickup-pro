"""Court listing and creation."""

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms import CourtForm
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
    form = CourtForm()
    if form.validate_on_submit():
        court = Court(
            name=form.name.data.strip(),
            address=form.address.data.strip(),
            lat=form.lat.data,
            lng=form.lng.data,
            created_by=current_user.id,
        )
        db.session.add(court)
        db.session.commit()
        flash("Court created successfully!")
        return redirect(url_for("courts.index"))

    return render_template("create_court.html", form=form)
