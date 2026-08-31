"""Every Spanish word a CLIENT reads, and the only module that holds one.

The register is docs/BRAND_VOICE.md §8, which is not §1: this reader is a customer standing in the
salon, not a colleague between clients. `tests/test_voice.py` discovers these by the
`*_CLIENT_COPY` suffix and gates them as their own audience — the `*_MSG`/`*_TEXT` sweep cannot
see them, and that separation is the whole reason the suffix differs.

**Nothing here assumes she is a woman.** The salon prices services for men as well, so a client
addressed as *la próxima* is one the copy has guessed at. Turn and number carry no article for
that reason, and a name is used where there is one.
"""

from __future__ import annotations

#: The page's own name. The salon's, not a product name.
TITLE_CLIENT_COPY = "Salón Aziza"

ASK_PHONE_CLIENT_COPY = "¿Cuál es tu teléfono?"
PHONE_HINT_CLIENT_COPY = "Diez dígitos, así: 8091234567"
ASK_NAME_CLIENT_COPY = "¿Cómo te llamas?"
ASK_AREAS_CLIENT_COPY = "¿Qué te vas a hacer hoy?"
WHICH_ONE_CLIENT_COPY = "¿Cuál de estos nombres es el tuyo?"
CONTINUE_CLIENT_COPY = "Continuar"

JOINED_CLIENT_COPY = "Listo, {name}. Ya estás en la fila."
ALREADY_CLIENT_COPY = "Ya estabas en la fila, {name}. No perdiste tu turno."
#: No article before the number, and none before "turno" either — see the module docstring.
POSITION_CLIENT_COPY = "Tu turno para {area}: número {position}."
POSITION_NEXT_CLIENT_COPY = "Para {area} sigues tú."
WAIT_CLIENT_COPY = "Espera aquí, que te llamamos por tu nombre."

BAD_PHONE_CLIENT_COPY = "Ese número no me cuadra. Escríbeme los diez dígitos."
NO_NAME_CLIENT_COPY = "Necesito tu nombre para poder llamarte."
NO_AREAS_CLIENT_COPY = "Escoge por lo menos una cosa."

#: The only failure that says what happened, and it says so because a stale code is the one a
#: real client actually hits — she scanned a second too late. Everything else is a 404 that
#: explains nothing, so a stranger poking at links learns nothing from the difference (§13).
EXPIRED_CLIENT_COPY = "Este código ya venció. Pídele a la especialista que te muestre el nuevo."
NOT_FOUND_CLIENT_COPY = "Este enlace no funciona. Pídele el código a la especialista."
CLOSED_CLIENT_COPY = "El salón está cerrado ahora mismo. Te esperamos cuando abramos."
