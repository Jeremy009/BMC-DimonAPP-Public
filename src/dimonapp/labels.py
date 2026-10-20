"""French labels of stored values, as shown in tables (FDS 3.4)."""

from dimonapp.models import AuthMethod, CompensationModel, DimonaStatus, DocumentType, Period

DIMONA_STATUS_LABELS = {
    DimonaStatus.NOT_APPLICABLE: 'Non applicable',
    DimonaStatus.OK: 'OK',
    DimonaStatus.PENDING: 'En attente',
    DimonaStatus.REJECTED: 'Refusée',
}
DOCUMENT_TYPE_LABELS = {
    DocumentType.CONTRACT: 'Contrat',
    DocumentType.QUALIFICATION: 'Qualification',
}
CANCELLED_LABEL = 'Annulée'
VALID_LABEL = 'Valide'
EXPIRED_LABEL = 'Expiré'
ACTIVE_LABEL = 'Actif'
INACTIVE_LABEL = 'Inactif'
COMPENSATION_MODEL_LABELS = {
    CompensationModel.HOURLY: 'Horaire',
    CompensationModel.FIXED: 'Prix fixe',
}
# What one rate pays for, as in "20,00 € / heure".
RATE_UNITS = {
    CompensationModel.HOURLY: 'heure',
    CompensationModel.FIXED: 'activité',
}
PERIOD_LABELS = {
    Period.Q1: 'T1',
    Period.Q2: 'T2',
    Period.Q3: 'T3',
    Period.Q4: 'T4',
    Period.YEAR: 'ANNÉE',
}
AUTH_METHOD_LABELS = {
    AuthMethod.LOCAL: "Nom d'utilisateur et mot de passe",
    AuthMethod.GOOGLE: 'Google',
}
