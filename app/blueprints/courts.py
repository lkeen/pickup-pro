"""Court listing and creation."""

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms import CourtForm
from app.models import Court
from app.services.aggregates import all_courts_brief, invalidate_courts
from app.services.geo import invalidate_area

bp = Blueprint("courts", __name__, url_prefix="/courts")


@bp.route("")
@login_required
def index():
    return render_template("courts.html", courts=all_courts_brief())


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
        # A cached search covering this location would not include the new
        # court. Drop those entries rather than serve them for the TTL.
        invalidate_area(court.lat, court.lng)
        invalidate_courts()
        flash("Court created successfully!")
        return redirect(url_for("courts.index"))

    return render_template("create_court.html", form=form)
