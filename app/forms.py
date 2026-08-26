"""Form definitions.

Every form in the app is a FlaskForm, which does two jobs at once: it renders a
CSRF token and it moves input validation off the view functions, where it was
previously a hand-rolled mix of `if not all([...])` checks and bare
`float()`/`int()` calls in try blocks.
"""

from flask_wtf import FlaskForm
from wtforms import (
    DateTimeLocalField,
    FloatField,
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    TextAreaField,
)
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange, Regexp

# Latitude/longitude bounds. Worth stating explicitly: the previous nearby-search
# guard treated 0 as "missing", which silently rejected the equator and the
# prime meridian.
LAT_RANGE = NumberRange(min=-90, max=90, message="Latitude must be between -90 and 90.")
LNG_RANGE = NumberRange(min=-180, max=180, message="Longitude must be between -180 and 180.")

MIN_PASSWORD_LENGTH = 10


class ConfirmForm(FlaskForm):
    """A form with no fields, used purely to carry a CSRF token.

    State-changing actions that need no input -- join, leave, logout -- still
    have to be POSTs with a token, or they can be triggered from another site.
    """


class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(max=64)])
    password = PasswordField("Password", validators=[DataRequired()])


class RegisterForm(FlaskForm):
    username = StringField(
        "Username",
        validators=[
            DataRequired(),
            Length(min=3, max=64),
            Regexp(
                r"^[A-Za-z0-9_.-]+$",
                message="Username may contain letters, numbers, dot, dash and underscore only.",
            ),
        ],
    )
    password = PasswordField(
        "Password",
        validators=[
            DataRequired(),
            Length(
                min=MIN_PASSWORD_LENGTH,
                message=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
            ),
        ],
    )


class CourtForm(FlaskForm):
    name = StringField("Court name", validators=[DataRequired(), Length(max=64)])
    address = StringField("Address", validators=[DataRequired(), Length(max=120)])
    # InputRequired rather than DataRequired: DataRequired treats 0.0 as absent.
    lat = FloatField("Latitude", validators=[InputRequired(), LAT_RANGE])
    lng = FloatField("Longitude", validators=[InputRequired(), LNG_RANGE])


class GameForm(FlaskForm):
    court_id = SelectField("Court", coerce=int, validators=[InputRequired()])
    time = DateTimeLocalField(
        "Date and time", format="%Y-%m-%dT%H:%M", validators=[DataRequired()]
    )
    max_players = IntegerField(
        "Max players", default=10, validators=[InputRequired(), NumberRange(min=2, max=20)]
    )

    def set_court_choices(self, courts):
        self.court_id.choices = [(court.id, f"{court.name} - {court.address}") for court in courts]
        return self


class StatsForm(FlaskForm):
    user_id = IntegerField(validators=[InputRequired()])
    points = IntegerField("Points", default=0, validators=[InputRequired(), NumberRange(min=0)])
    rebounds = IntegerField("Rebounds", default=0, validators=[InputRequired(), NumberRange(min=0)])
    assists = IntegerField("Assists", default=0, validators=[InputRequired(), NumberRange(min=0)])


class RatingForm(FlaskForm):
    to_user_id = IntegerField(validators=[InputRequired()])
    rating = SelectField(
        "Rating",
        coerce=int,
        choices=[
            (1, "1 - Poor"),
            (2, "2 - Below Average"),
            (3, "3 - Average"),
            (4, "4 - Good"),
            (5, "5 - Excellent"),
        ],
        validators=[InputRequired(), NumberRange(min=1, max=5)],
    )
    comment = TextAreaField("Comment", validators=[Length(max=1000)])
