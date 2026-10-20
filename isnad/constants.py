"""Model constants (spec section 3)."""

A0 = 8  # minimum age (lunar years) at which a student can have heard from the teacher
MU_AGE = 68.0  # mean lifespan, used to impute missing birth/death
SD_AGE = 14.0
# Lifespan bounds (years). v1 edge scoring (isnad.score) does not apply them; v2 dating
# (isnad.dating) enforces AGE_MIN <= death - birth <= AGE_MAX as hard constraints.
AGE_MIN = 20
AGE_MAX = 100
GAP_THRESHOLD = 0.05
SUSPECT_THRESHOLD = 0.2
CONFLICT_YEARS = 20

EXPLICIT_TERMS = {"حدثنا", "حدثني", "أخبرنا", "أخبرني", "سمعت", "سمعنا", "أنبأنا", "أنبأني",
                  "قرأت على", "قرئ على"}
AMBIGUOUS_TERMS = {"عن", "أن", "قال", "ذكر", "روى", "يرويه", None}

# Classification is by normalised prefix (isnad.dates._norm: hamza forms -> ا, ة -> ه, ى -> ي,
# diacritics stripped), so write these in normalised form. Original Arabic in comments.
EXPLICIT_PREFIXES = (
    "حدث",       # حدث: حدثنا/حدثني/حدثه/حدثهم/حدثتني
    "اخبر",      # أخبر: أخبرنا/أخبرني/أخبره/أخبرته/أخبراه
    "سمع",       # سمع: سمعت/سمعنا
    "انبا",      # أنبأ: أنبأنا/أنبأني
    "نبا",       # نبأ
    "قرات على",  # قرأت على
    "قرئ على",
    "قراتنا",    # قرأتنا
    "قرانا",     # قرأنا
    "سال",       # سأل: سألت/سأل/سألنا
    "رايت",      # رأيت
    "راي",       # رأى
    "شهدت",      # شهدت
    "كتب الي",   # كتب إلي
    "قال لي",    # قال لي
    "قال لنا",   # قال لنا
    "قراءه عليه",  # قراءة عليه وأنا أسمع
    "فيما قرئ عليه",
    "فيما قرأ",
    "لقي",       # لقيت/لقيته
    "اسمعت",     # أسمعت
    "حفظناه من",  # حفظناه من
    "دخلت على",  # دخلت على
    "اتيت",      # أتيت
    "كتب",       # كتب إلي/كتب لي
    "قلت",       # قلت/قلت له (direct address = audition)
    "قلنا",      # قلنا
    "خطب",       # خطب/خطبنا (heard a sermon)
)
AMBIGUOUS_PREFIXES = (
    "عن",        # عن
    "ان",        # أن
    "قال",       # قال/قالت (قال لي/لنا matched earlier as explicit)
    "فقال",      # فقال
    "ذكر",       # ذكر
    "روي",       # روى
    "يروي",      # يروي/يرويه
    "يحدث عن",   # يحدث عن
    "بلغ",       # بلغ/بلغني
    "يحدث",      # يحدث/يحدثان
    "يخبر عن",   # يخبر عن
    "يذكر عن",   # يذكر عن
    "يقول",      # يقول
    "سئل",       # سئل
    "زعم",       # زعم
)
EXPLICIT_EXACT = {"صريح في السماع", "نا", "ثنا", "انا"}  # نا/ثنا/أنا: scribal abbreviations; exact so نافع is not captured
AMBIGUOUS_EXACT = {"في حكم العنعنه", "قيل"}  # في حكم العنعنة

# Passive formulae ("it was narrated to me"): the narrator did not hear directly -> ambiguous.
# Checked before the explicit roots; "<explicit root> عن" is handled in classify_term.
PASSIVE_EXACT = {"اخبرت", "نبئت", "انبئت"}
PASSIVE_PREFIXES = ("حدثت عن", "حدثت ان", "اخبرت عن", "اخبرت ان", "نبئت", "انبئت")

# Narrator dating by difference constraints (isnad.dating)
MAX_ITER = 50  # propagation rounds per pass
HOLDOUT_FOLDS = 5
DATE_K = 2  # known date interval = year +- DATE_K * max(sd, 1)
YEAR_LO, YEAR_HI = 0, 1500  # prior bounds (AH) for unknown birth/death
# Unknown births may precede the Hijra (early Companions died before 20 AH: 82 recorded deaths
# < 20), so the birth prior opens AGE_MAX years below YEAR_LO; with [0, 1500] those deaths would
# be infeasible before any link is read.
BIRTH_LO = YEAR_LO - AGE_MAX

# Common links (isnad.tree): branch thresholds k for the k-common-link of a merged chain tree
K_CL = (2, 3)

# Release checks (isnad.export_hf): groups re-aligned with difflib to verify the site's segments
ALIGN_SAMPLE = 500
