from apps.core.errors import Conflict


class ProgramError(Conflict):
    default_code = "program_error"
