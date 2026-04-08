"""Default scope for the public web app.

The site is intentionally limited to Canadian lifters competing in IPF-sanctioned
meets (which includes all CPU domestic meets — CPU is Canada's IPF national
affiliate). This is enforced as default values on the API endpoints, not at the
parquet level, so the scope can be widened later without re-preprocessing.
"""

DEFAULT_COUNTRY = "Canada"
DEFAULT_PARENT_FEDERATION = "IPF"
