"""Blueprints POST/DELETE (mutations)."""
import re

from fastapi import APIRouter, Form, HTTPException, Request

from app import config, docker_client, ksf_commands
from app.helpers import (
    action_result,
    audit_log,
    client_actor,
    require_action,
    require_valid_app,
    require_valid_container,
    run_app_action,
    save_full_output,
    validate_port,
    validate_subdomain,
)
from app.services import backups as backups_svc, jobs, webhooks

router = APIRouter()


# ── Container actions ──────────────────────────────────────

@router.post("/containers/{container_id}/restart")
async def container_restart(container_id: str, request: Request):
    require_action()
    require_valid_container(container_id)
    ok = docker_client.restart_container(container_id)
    await audit_log(request, "container.restart", container_id)
    return action_result(ok, f"Container {container_id} redemarre." if ok else f"Echec du redemarrage de {container_id}.")


@router.post("/containers/{container_id}/stop")
async def container_stop(container_id: str, request: Request):
    require_action()
    require_valid_container(container_id)
    ok = docker_client.stop_container(container_id)
    await audit_log(request, "container.stop", container_id)
    return action_result(ok, f"Container {container_id} arrete." if ok else f"Echec de l'arret de {container_id}.")


@router.post("/containers/{container_id}/start")
async def container_start(container_id: str, request: Request):
    require_action()
    require_valid_container(container_id)
    ok = docker_client.start_container(container_id)
    await audit_log(request, "container.start", container_id)
    return action_result(ok, f"Container {container_id} demarre." if ok else f"Echec du demarrage de {container_id}.")


# ── App actions ────────────────────────────────────────────

@router.post("/apps/{app_name}/install")
async def app_install(
    app_name: str,
    request: Request,
    subdomain: str = Form(...),
    port: str = Form(...),
    protected: str = Form("false"),
):
    require_action()
    require_valid_app(app_name)
    available = ksf_commands.list_available_apps()
    template = next((a for a in available if a["name"] == app_name), None)
    if not template or template["installed"]:
        raise HTTPException(status_code=400, detail="Application non disponible")

    err = validate_subdomain(subdomain) or validate_port(port)
    if err:
        raise HTTPException(status_code=400, detail=err)

    extra_args = ["--subdomain", subdomain, "--port", port]
    if protected.lower() in ("true", "on", "1"):
        extra_args.append("--auth")
    else:
        extra_args.append("--no-auth")

    ok, output = await ksf_commands.run_app_command(app_name, "install", extra_args=extra_args)
    log_path = save_full_output(f"install-{app_name}", output) if ok or output else ""
    await audit_log(request, "app.install", app_name,
                    after={"subdomain": subdomain, "port": port, "protected": protected})
    return action_result(
        ok,
        f"Installation de {app_name} lancee." if ok else f"Echec de l'installation de {app_name}.",
        output,
        log_path=log_path or None,
    )


@router.post("/apps/{app_name}/update")
async def app_update(app_name: str):
    require_action()
    require_valid_app(app_name)
    return await run_app_action(
        app_name, "update",
        success_msg=f"Mise a jour de {app_name} lancee.",
        fail_msg=f"Echec de la mise a jour de {app_name}.",
    )


@router.post("/apps/{app_name}/restart")
async def app_restart(app_name: str):
    require_action()
    require_valid_app(app_name)
    return await run_app_action(
        app_name, "restart",
        success_msg=f"Redemarrage de {app_name} lance.",
        fail_msg=f"Echec du redemarrage de {app_name}.",
    )


@router.post("/apps/{app_name}/start")
async def app_start(app_name: str):
    require_action()
    require_valid_app(app_name)
    return await run_app_action(
        app_name, "start",
        success_msg=f"Demarrage de {app_name} lance.",
        fail_msg=f"Echec du demarrage de {app_name}.",
    )


@router.post("/apps/{app_name}/stop")
async def app_stop(app_name: str):
    require_action()
    require_valid_app(app_name)
    return await run_app_action(
        app_name, "stop",
        success_msg=f"Arret de {app_name} lance.",
        fail_msg=f"Echec de l'arret de {app_name}.",
    )


@router.post("/apps/{app_name}/disable")
async def app_disable(app_name: str):
    require_action()
    require_valid_app(app_name)
    return await run_app_action(
        app_name, "disable",
        success_msg=f"Desactivation de {app_name} lancee.",
        fail_msg=f"Echec de la desactivation de {app_name}.",
    )


@router.post("/apps/{app_name}/remove")
async def app_remove(app_name: str, request: Request):
    require_action()
    require_valid_app(app_name)
    return await run_app_action(
        app_name, "remove", request=request, audit_action="app.remove",
        success_msg=f"Suppression de {app_name} lancee.",
        fail_msg=f"Echec de la suppression de {app_name}.",
    )


# ── Backup actions ─────────────────────────────────────────

@router.post("/backups/create")
async def backup_create():
    require_action()
    job = await jobs.enqueue(
        "backup.create",
        [config.REPO_DIR + "/ksf.sh", "backup", "create", "--yes"],
        lock_key="backup",
        triggered_by="admin",
    )
    return {"success": True, "message": "Backup lance en arriere-plan.", "job_id": job["id"]}


@router.post("/backups/verify")
async def backup_verify():
    require_action()
    job = await jobs.enqueue(
        "backup.verify",
        [config.REPO_DIR + "/ksf.sh", "backup", "verify", "latest"],
        triggered_by="admin",
    )
    return {"success": True, "message": "Verification lancee en arriere-plan.", "job_id": job["id"]}


@router.post("/backups/restore-dryrun")
async def backup_restore_dryrun():
    require_action()
    job = await jobs.enqueue(
        "backup.verify",
        [config.REPO_DIR + "/ksf.sh", "backup", "restore", "latest", "--dry-run"],
        triggered_by="admin",
    )
    return {"success": True, "message": "Simulation lancee en arriere-plan.", "job_id": job["id"]}


@router.post("/backups/{backup_name}/delete")
async def backup_delete(backup_name: str, request: Request):
    require_action()
    ok, msg = backups_svc.delete_backup(backup_name)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    await audit_log(request, "backup.delete", backup_name)
    return {"success": True, "message": msg}


@router.post("/backups/{backup_name}/restore")
async def backup_restore(backup_name: str, request: Request):
    require_action()
    if backups_svc._safe_path(backup_name) is None:
        raise HTTPException(status_code=400, detail="Nom de backup invalide")
    job = await jobs.enqueue(
        "backup.restore",
        [config.REPO_DIR + "/ksf.sh", "backup", "restore", backup_name, "--yes"],
        lock_key="backup-restore",
        triggered_by=client_actor(request),
    )
    await audit_log(request, "backup.restore", backup_name, job_id=job["id"])
    return {"success": True, "message": "Restauration lancee en arriere-plan.", "job_id": job["id"]}


@router.post("/backups/{backup_name}/verify")
async def backup_verify_one(backup_name: str, request: Request):
    require_action()
    if backups_svc._safe_path(backup_name) is None:
        raise HTTPException(status_code=400, detail="Nom de backup invalide")
    job = await jobs.enqueue(
        "backup.verify",
        [config.REPO_DIR + "/ksf.sh", "backup", "verify", backup_name],
        triggered_by=client_actor(request),
    )
    await audit_log(request, "backup.verify", backup_name, job_id=job["id"])
    return {"success": True, "message": "Verification lancee.", "job_id": job["id"]}


@router.post("/backups/prune")
async def backup_prune(request: Request, keep: int = 5):
    require_action()
    if not (1 <= keep <= 100):
        raise HTTPException(status_code=400, detail="Valeur --keep doit être entre 1 et 100")
    job = await jobs.enqueue(
        "backup.prune",
        [config.REPO_DIR + "/ksf.sh", "backup", "prune", "--keep", str(keep), "--yes"],
        triggered_by=client_actor(request),
    )
    await audit_log(request, "backup.prune", after={"keep": keep}, job_id=job["id"])
    return {"success": True, "message": f"Purge en cours (garder {keep}).", "job_id": job["id"]}


# ── Jobs ───────────────────────────────────────────────────

@router.post("/jobs/{job_id}/cancel")
async def job_cancel(job_id: str):
    require_action()
    ok = await jobs.cancel(job_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Job non annulable")
    return {"success": True}


# ── Notifications ──────────────────────────────────────────

@router.post("/notifications/{notif_id}/read")
async def notification_read(notif_id: str):
    await notifications.mark_read(notif_id)
    return {"success": True}


@router.post("/notifications/read-all")
async def notification_read_all():
    n = await notifications.mark_all_read()
    return {"success": True, "marked": n}


@router.delete("/notifications/{notif_id}")
async def notification_delete(notif_id: str):
    ok = await notifications.delete(notif_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Notification introuvable")
    return {"success": True}


# ── Webhooks ───────────────────────────────────────────────

@router.post("/api/webhooks")
async def webhook_create(request: Request):
    body = await request.json()
    name = (body.get("name") or "").strip()
    url = (body.get("url") or "").strip()
    events_list = body.get("events") or ["*"]
    secret = (body.get("secret") or "").strip() or None
    if not name or not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="name et url (http/https) requis")
    ok, err = webhooks._is_safe_webhook_target(url, allow_private=False)
    if not ok:
        raise HTTPException(status_code=400, detail=f"URL refusée : {err}")
    try:
        eid = await webhooks.create(name, url, events_list, secret)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    await audit_log(request, "webhook.create", eid, after={"name": name})
    return {"success": True, "id": eid}


@router.post("/api/webhooks/{endpoint_id}")
async def webhook_update(endpoint_id: str, request: Request):
    body = await request.json()
    if "url" in body:
        ok, err = webhooks._is_safe_webhook_target(str(body["url"]), allow_private=False)
        if not ok:
            raise HTTPException(status_code=400, detail=f"URL refusée : {err}")
    await webhooks.update(endpoint_id, **body)
    await audit_log(request, "webhook.update", endpoint_id, after=body)
    return {"success": True}


@router.delete("/api/webhooks/{endpoint_id}")
async def webhook_delete(endpoint_id: str, request: Request):
    ok = await webhooks.delete(endpoint_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Webhook introuvable")
    await audit_log(request, "webhook.delete", endpoint_id)
    return {"success": True}


@router.post("/api/webhooks/{endpoint_id}/test")
async def webhook_test(endpoint_id: str, request: Request):
    ep = await webhooks.get(endpoint_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Webhook introuvable")
    payload = {
        "test": True,
        "title": "Test webhook ksf-web",
        "body": f"Ceci est un test envoyé à {ep['name']}.",
        "level": "info",
        "category": "test",
    }
    await webhooks._send_with_retry(ep, payload)
    return {"success": True}


# ── System actions ─────────────────────────────────────────

@router.post("/security/refresh")
async def security_refresh():
    require_action()
    results = {}
    try:
        ksf_env = ksf_commands.get_ksf_env()
        if ksf_env.get("WITH_CROWDSEC", "false").lower() == "true":
            ok1, out1 = await ksf_commands.run_command("crowdsec_alerts")
            log1 = save_full_output("crowdsec-alerts", out1)
            results["alerts"] = action_result(ok1, "Alertes rafraichies.", out1, log_path=log1 or None)
            ok2, out2 = await ksf_commands.run_command("crowdsec_bouncers")
            log2 = save_full_output("crowdsec-bouncers", out2)
            results["bouncers"] = action_result(ok2, "Bouncers rafraichis.", out2, log_path=log2 or None)
    except Exception:
        pass
    return results


@router.post("/system/doctor")
async def system_doctor():
    require_action()
    job = await jobs.enqueue(
        "system.doctor",
        [config.REPO_DIR + "/ksf.sh", "doctor"],
        triggered_by="admin",
    )
    return {"success": True, "message": "Diagnostic lance en arriere-plan.", "job_id": job["id"]}


@router.post("/system/update-all")
async def system_update_all():
    require_action()
    job = await jobs.enqueue(
        "system.update",
        [config.REPO_DIR + "/ksf.sh", "update", "all", "--yes"],
        lock_key="system-update",
        triggered_by="admin",
    )
    return {"success": True, "message": "Mise a jour lancee en arriere-plan.", "job_id": job["id"]}


@router.post("/system/update-service")
async def system_update_service(request: Request, service: str = ""):
    """Update ciblé d'une stack système (crowdsec|traefik|oauth2|all)."""
    require_action()
    if service not in ("crowdsec", "traefik", "oauth2", "all"):
        raise HTTPException(status_code=400, detail="service doit être crowdsec|traefik|oauth2|all")
    job = await jobs.enqueue(
        "system.update_service",
        [config.REPO_DIR + "/ksf.sh", "update", service, "--yes"],
        lock_key="system-update",
        triggered_by=client_actor(request),
    )
    await audit_log(request, "system.update_service", service, job_id=job["id"])
    return {"success": True, "message": f"Update de {service} lance.", "job_id": job["id"]}


@router.post("/system/restart")
async def system_restart(request: Request):
    """Restart plateforme (Traefik, OAuth2 Proxy, CrowdSec). Downtime ~5s."""
    require_action()
    job = await jobs.enqueue(
        "system.restart",
        [config.REPO_DIR + "/ksf.sh", "restart", "--yes"],
        lock_key="platform-restart",
        triggered_by=client_actor(request),
    )
    await audit_log(request, "system.restart", job_id=job["id"])
    return {"success": True, "message": "Restart plateforme lance. Downtime ~5s attendu.", "job_id": job["id"]}


# ── Apps rebuild ───────────────────────────────────────────

@router.post("/apps/{app_name}/rebuild")
async def app_rebuild(app_name: str, request: Request, force: str = "false"):
    """Re-pull image + relance les containers d'une app.

    Refusé par défaut sur une app désactivée (APP_DISABLED=true) car le
    rebuild re-crée les containers et routes Traefik que l'user avait
    explicitement retirés. Passer `?force=true` pour outrepasser.
    """
    require_action()
    require_valid_app(app_name)
    if force.lower() not in ("true", "1", "yes", "on"):
        env = ksf_commands.get_installed_app_env(app_name)
        if env.get("APP_DISABLED", "false").lower() == "true":
            raise HTTPException(
                status_code=400,
                detail=f"{app_name} est désactivée. Rebuild refusé pour éviter de recréer des containers/routes. "
                       f"Réactivez d'abord l'app ou passez ?force=true."
            )
    job = await jobs.enqueue(
        "app.rebuild",
        [config.REPO_DIR + "/app.sh", "rebuild", app_name, "--yes"],
        lock_key=f"app-rebuild-{app_name}",
        triggered_by=client_actor(request),
    )
    await audit_log(request, "app.rebuild", app_name,
                    after={"force": force.lower() in ("true", "1", "yes", "on")},
                    job_id=job["id"])
    return {"success": True, "message": f"Rebuild de {app_name} lance.", "job_id": job["id"]}


# ── CrowdSec actions ──────────────────────────────────────

_DURATION_RE = re.compile(r"^[0-9]+[mhd]$")


@router.post("/security/crowdsec/ban")
async def crowdsec_ban(request: Request, ip: str = "", duration: str = "10m"):
    """Bannir une IP via CrowdSec (durée: ex 10m, 24h, 7d)."""
    require_action()
    if not re.fullmatch(r"^[0-9]{1,3}(\.[0-9]{1,3}){3}$|^[0-9a-fA-F:]+$", ip):
        raise HTTPException(status_code=400, detail="IP invalide (IPv4 ou IPv6)")
    if not _DURATION_RE.match(duration):
        raise HTTPException(status_code=400, detail="duration doit matcher ^[0-9]+[mhd]$ (ex: 10m, 24h, 7d)")
    job = await jobs.enqueue(
        "ksf.crowdsec_ban",
        [config.REPO_DIR + "/ksf.sh", "crowdsec", "ban", ip, duration],
        triggered_by=client_actor(request),
    )
    await audit_log(request, "crowdsec.ban", ip, after={"duration": duration}, job_id=job["id"])
    return {"success": True, "message": f"Ban {ip} pour {duration} lance.", "job_id": job["id"]}


@router.post("/security/crowdsec/unban")
async def crowdsec_unban(request: Request, ip: str = ""):
    """Débannir une IP."""
    require_action()
    if not re.fullmatch(r"^[0-9]{1,3}(\.[0-9]{1,3}){3}$|^[0-9a-fA-F:]+$", ip):
        raise HTTPException(status_code=400, detail="IP invalide (IPv4 ou IPv6)")
    job = await jobs.enqueue(
        "ksf.crowdsec_unban",
        [config.REPO_DIR + "/ksf.sh", "crowdsec", "unban", ip],
        triggered_by=client_actor(request),
    )
    await audit_log(request, "crowdsec.unban", ip, job_id=job["id"])
    return {"success": True, "message": f"Unban {ip} lance.", "job_id": job["id"]}


@router.post("/security/crowdsec/flush")
async def crowdsec_flush(request: Request):
    """Flush toutes les décisions CrowdSec."""
    require_action()
    job = await jobs.enqueue(
        "ksf.crowdsec_flush",
        [config.REPO_DIR + "/ksf.sh", "crowdsec", "flush-decisions", "--yes"],
        triggered_by=client_actor(request),
    )
    await audit_log(request, "crowdsec.flush", job_id=job["id"])
    return {"success": True, "message": "Flush des decisions lance.", "job_id": job["id"]}


@router.post("/security/crowdsec/restart")
async def crowdsec_restart(request: Request):
    """Restart service CrowdSec."""
    require_action()
    job = await jobs.enqueue(
        "ksf.crowdsec_restart",
        [config.REPO_DIR + "/ksf.sh", "crowdsec", "restart"],
        triggered_by=client_actor(request),
    )
    await audit_log(request, "crowdsec.restart", job_id=job["id"])
    return {"success": True, "message": "Restart CrowdSec lance.", "job_id": job["id"]}


# ── AppSec / WAF ───────────────────────────────────────────

@router.post("/security/appsec/toggle")
async def appsec_toggle(request: Request, enabled: str = ""):
    """Activer ou désactiver AppSec (CROWDSEC_APPSEC_ENABLED)."""
    require_action()
    if enabled not in ("true", "false", "on", "off", "1", "0"):
        raise HTTPException(status_code=400, detail="enabled doit être true|false")
    state = enabled.lower() in ("true", "on", "1")
    job = await jobs.enqueue(
        "ksf.appsec_toggle",
        [config.REPO_DIR + "/ksf.sh", "crowdsec", "appsec",
         "enable" if state else "disable", "--yes"],
        triggered_by=client_actor(request),
    )
    await audit_log(request, "appsec.toggle", target="appsec",
                    after={"enabled": state}, job_id=job["id"])
    return {"success": True, "message": f"AppSec {'activation' if state else 'desactivation'} lancee.", "job_id": job["id"]}


# ── Trusted IPs (Cloudflare) ───────────────────────────────

@router.post("/security/trusted-ips/apply")
async def trusted_ips_apply(request: Request, provider: str = "cloudflare"):
    """Appliquer les CIDR Cloudflare comme trusted IPs Traefik (restart Traefik)."""
    require_action()
    if provider not in ("cloudflare",):
        raise HTTPException(status_code=400, detail="provider doit être 'cloudflare'")
    job = await jobs.enqueue(
        "ksf.trusted_ips_apply",
        [config.REPO_DIR + "/ksf.sh", "trusted-ips", "apply", provider, "--yes"],
        lock_key="traefik-restart",
        triggered_by=client_actor(request),
    )
    await audit_log(request, "trusted_ips.apply", target=provider, job_id=job["id"])
    return {"success": True, "message": f"Application des CIDR {provider} lancee.", "job_id": job["id"]}


# ── Clean-data (données préservées d'une app) ─────────────

@router.post("/data/{app_name}/remove")
async def clean_data_remove(app_name: str, request: Request):
    """Supprime les données préservées d'une app (clean-data)."""
    require_action()
    require_valid_app(app_name)
    job = await jobs.enqueue(
        "system.clean_data",
        [config.REPO_DIR + "/ksf.sh", "clean-data", app_name, "--yes"],
        triggered_by=client_actor(request),
    )
    await audit_log(request, "clean_data.remove", app_name, job_id=job["id"])
    return {"success": True, "message": f"Suppression des donnees de {app_name} lancee.", "job_id": job["id"]}
