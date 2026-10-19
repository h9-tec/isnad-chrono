"""Model constants (spec section 3)."""

A0 = 8  # minimum age (lunar years) at which a student can have heard from the teacher
MU_AGE = 68.0  # mean lifespan, used to impute missing birth/death
SD_AGE = 14.0
AGE_MIN = 20  # documented truncation bounds of the lifespan prior (closed form ignores them in v1)
AGE_MAX = 100
GAP_THRESHOLD = 0.05
SUSPECT_THRESHOLD = 0.2
CONFLICT_YEARS = 20

EXPLICIT_TERMS = {"حدثنا", "حدثني", "أخبرنا", "أخبرني", "سمعت", "سمعنا", "أنبأنا", "أنبأني",
                  "قرأت على", "قرئ على"}
AMBIGUOUS_TERMS = {"عن", "أن", "قال", "ذكر", "روى", "يرويه", None}
