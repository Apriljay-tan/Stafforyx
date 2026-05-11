import os
import uuid

# Store the machine ID file one level up from this file (= project root)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ID_FILE = os.path.join(_PROJECT_ROOT, '.stafforyx_machine_id')


def get_machine_id() -> str:
    """
    Return a stable, installation-specific Machine ID.

    On first call the ID is generated from a UUID4, written to
    .stafforyx_machine_id in the project root, and reused on every
    subsequent call.  Deleting that file is the only way to reset it.

    Format: STX-MACHINE-XXXX-XXXX-XXXX  (12 uppercase hex digits)
    """
    if os.path.isfile(_ID_FILE):
        stored = open(_ID_FILE, encoding='utf-8').read().strip()
        if stored.startswith('STX-MACHINE-'):
            return stored

    hex32 = uuid.uuid4().hex.upper()
    machine_id = f'STX-MACHINE-{hex32[0:4]}-{hex32[4:8]}-{hex32[8:12]}'

    with open(_ID_FILE, 'w', encoding='utf-8') as f:
        f.write(machine_id)

    return machine_id
