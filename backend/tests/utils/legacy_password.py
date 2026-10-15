# Synthetic fixture only: bcrypt, cost 4, fixed public test salt.
LEGACY_PASSWORD = "synthetic-legacy-password"
LEGACY_BCRYPT_HASH = "$2b$04$abcdefghijklmnopqrstuup3hL86V1359pjZDqRJnAPlGpp1eqJ9W"
INVALID_PASSWORD_HASHES = (
    "",
    "not-a-password-hash",
    LEGACY_BCRYPT_HASH[:-1],
    LEGACY_BCRYPT_HASH.replace("$04$", "$03$"),
    "$argon2id$v=19$m=65536,t=3,p=4$invalid$invalid",
    "$pbkdf2-sha256$29000$c2FsdA$unsupported",
)
