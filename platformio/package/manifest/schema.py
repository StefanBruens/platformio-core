# Copyright (c) 2014-present PlatformIO <contact@platformio.org>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import requests
import semantic_version
from marshmallow import Schema, ValidationError, fields, validate, validates
from marshmallow import __version_info__ as marshmallow_version
from marshmallow import EXCLUDE as marshmallow_EXCLUDE

from platformio.package.exception import ManifestValidationError
from platformio.util import memoized


class StrictSchema(Schema):
    def handle_error(self, error, data, *, many, **_kwargs):
        # skip broken records
        if self.many:
            data = [
                item for idx, item in enumerate(data) if idx not in error.messages
            ]
            raise ValidationError(message=error.messages,
                                  data=error.data, valid_data=data)
        raise ValidationError(message=error.messages, data=error.data, valid_data=None)


class StrictListField(fields.List):
    def _deserialize(self, value, attr, data, **kwargs):
        try:
            if marshmallow_version >= (3, ):
                return super(StrictListField, self)._deserialize(value, attr, data, **kwargs)
            return super(StrictListField, self)._deserialize(value, attr, data)
        except ValidationError as exc:
            if exc.data:
                exc.data = [item for item in exc.data if item is not None]
            raise exc


class AuthorSchema(StrictSchema):
    name = fields.Str(required=True, validate=validate.Length(min=1, max=50))
    email = fields.Email(validate=validate.Length(min=1, max=50))
    maintainer = fields.Bool(default=False)
    url = fields.Url(validate=validate.Length(min=1, max=255))


class RepositorySchema(StrictSchema):
    type = fields.Str(
        required=True,
        validate=validate.OneOf(
            ["git", "hg", "svn"],
            error="Invalid repository type, please use one of [git, hg, svn]",
        ),
    )
    url = fields.Str(required=True, validate=validate.Length(min=1, max=255))
    branch = fields.Str(validate=validate.Length(min=1, max=50))


class ExportSchema(Schema):
    include = StrictListField(fields.Str)
    exclude = StrictListField(fields.Str)


class ExampleSchema(StrictSchema):
    name = fields.Str(
        required=True,
        validate=[
            validate.Length(min=1, max=100),
            validate.Regexp(
                r"^[a-zA-Z\d\-\_/]+$", error="Only [a-zA-Z0-9-_/] chars are allowed"
            ),
        ],
    )
    base = fields.Str(required=True)
    files = StrictListField(fields.Str, required=True)


class ManifestSchema(Schema):
    def __init__(self, **kwargs):
        if marshmallow_version >= (3, ):
            self.strict = kwargs.pop('strict', False)
        Schema.__init__(self, **kwargs)

    class Meta:
        # EXCLUDE unknown keys, keep marshmallow 2 behavior
        if marshmallow_version >= (3, ):
            unknown = marshmallow_EXCLUDE

    # Required fields
    name = fields.Str(required=True, validate=validate.Length(min=1, max=100))
    version = fields.Str(required=True, validate=validate.Length(min=1, max=50))

    # Optional fields

    authors = fields.Nested(AuthorSchema, many=True)
    description = fields.Str(validate=validate.Length(min=1, max=1000))
    homepage = fields.Url(validate=validate.Length(min=1, max=255))
    license = fields.Str(validate=validate.Length(min=1, max=255))
    repository = fields.Nested(RepositorySchema)
    export = fields.Nested(ExportSchema)
    examples = fields.Nested(ExampleSchema, many=True)

    keywords = StrictListField(
        fields.Str(
            validate=[
                validate.Length(min=1, max=50),
                validate.Regexp(
                    r"^[a-z\d\-\+\. ]+$", error="Only [a-z0-9-+. ] chars are allowed"
                ),
            ]
        )
    )

    platforms = StrictListField(
        fields.Str(
            validate=[
                validate.Length(min=1, max=50),
                validate.Regexp(
                    r"^([a-z\d\-_]+|\*)$", error="Only [a-z0-9-_*] chars are allowed"
                ),
            ]
        )
    )
    frameworks = StrictListField(
        fields.Str(
            validate=[
                validate.Length(min=1, max=50),
                validate.Regexp(
                    r"^([a-z\d\-_]+|\*)$", error="Only [a-z0-9-_*] chars are allowed"
                ),
            ]
        )
    )

    # platform.json specific
    title = fields.Str(validate=validate.Length(min=1, max=100))

    # package.json specific
    system = StrictListField(
        fields.Str(
            validate=[
                validate.Length(min=1, max=50),
                validate.Regexp(
                    r"^[a-z\d\-_]+$", error="Only [a-z0-9-_] chars are allowed"
                ),
            ]
        )
    )

    # Wrapper to encapsulate differences between marshmallow 2 and 3
    # load() method
    def load_manifest(self, manifest):
        if marshmallow_version >= (3, ):
            try:
                data = self.load(manifest)
            except ValidationError as exc:
                return (exc.valid_data, exc.messages)
            else:
                return (data, None)
        else:
            return self.load(manifest)

    def handle_error(self, error, data, *, many, **_kwargs):
        if self.strict:
            raise ManifestValidationError(error, data)

    @validates("version")
    def validate_version(self, value):  # pylint: disable=no-self-use
        try:
            value = str(value)
            assert "." in value
            semantic_version.Version.coerce(value)
        except (AssertionError, ValueError):
            raise ValidationError(
                "Invalid semantic versioning format, see https://semver.org/"
            )

    @validates("license")
    def validate_license(self, value):
        try:
            spdx = self.load_spdx_licenses()
        except requests.exceptions.RequestException:
            raise ValidationError("Could not load SPDX licenses for validation")
        for item in spdx.get("licenses", []):
            if item.get("licenseId") == value:
                return
        raise ValidationError(
            "Invalid SPDX license identifier. See valid identifiers at "
            "https://spdx.org/licenses/"
        )

    @staticmethod
    @memoized(expire="1h")
    def load_spdx_licenses():
        r = requests.get(
            "https://raw.githubusercontent.com/spdx/license-list-data"
            "/v3.6/json/licenses.json"
        )
        r.raise_for_status()
        return r.json()
