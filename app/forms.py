"""Form definitions.

Every form is a FlaskForm, which renders a CSRF token and keeps input
validation out of the view functions.
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
from wtforms.validators import (
    DataRequired,
    Email,
    InputRequired,
    Length,
    NumberRange,
    Regexp,
)

LAT_RANGE = NumberRange(min=-90, max=90, message="Latitude must be between -90 and 90.")
LNG_RANGE = NumberRange(min=-180, max=180, message="Longitude must be between -180 and 180.")

MIN_PASSWORD_LENGTH = 10


class ConfirmForm(FlaskForm):
    """A fieldless form, used purely to carry a CSRF token.

    State-changing actions that need no input -- join, leave, logout -- still
    have to be POSTs with a token, or another site can trigger them.
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
    email = StringField(
        "Email",
        validators=[DataRequired(), Email(), Length(max=254)],
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
    # InputRequired rather than DataRequired: DataRequired treats 0.0 as absent,
    # and the equator is a real place.
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
        """Populate the court options, which is also what validates the id."""
        self.court_id.choices = [
            (court["id"], f"{court['name']} - {court['address']}") for court in courts
        ]
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
