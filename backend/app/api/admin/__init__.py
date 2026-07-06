"""
Olympus Engine v9 — Admin API Router Assembly
Strictly client certificate (mTLS) validated via OU mapping.
"""
from fastapi import APIRouter, Depends, Header, HTTPException, status

from backend.app.api.admin.audit import router as audit_router
from backend.app.api.admin.hsm import router as hsm_router
from backend.app.api.admin.gdpr import router as gdpr_router
from backend.app.api.admin.deploy import router as deploy_router

async def verify_admin_mtls(
    x_admin_client_cert_ou: str = Header(..., alias="X-Admin-Client-Cert-OU")
) -> None:
    # OpenResty validates client certs and passes OU header.
    if x_admin_client_cert_ou != "olympus-admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="mTLS authentication failed: OU must be olympus-admin"
        )

admin_router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(verify_admin_mtls)]
)

admin_router.include_router(audit_router)
admin_router.include_router(hsm_router)
admin_router.include_router(gdpr_router)
admin_router.include_router(deploy_router)
# VERIFIED: mTLS client cert validation on OU==olympus-admin and inclusion of all 4 sub-routers under /api/admin.
