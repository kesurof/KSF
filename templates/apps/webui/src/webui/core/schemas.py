from pydantic import BaseModel, Field
from typing import Optional


class InstallRequest(BaseModel):
    template: str
    instance: str = ""
    subdomain: str = ""
    domain: str = ""
    host: str = ""
    host_port: str = ""
    port: str = ""
    auth: Optional[bool] = None
    no_auth: bool = False
    local_only: bool = False


class ConfirmRequest(BaseModel):
    confirmed: bool = False


class ConfigureRequest(ConfirmRequest):
    subdomain: str = ""
    domain: str = ""
    host: str = ""
    host_port: str = ""
    no_host_port: bool = False
    local_only: Optional[bool] = None
class RemoveRequest(ConfirmRequest):
    remove_data: bool = False


class OperationRequest(ConfirmRequest):
    dry_run: bool = False


class CrowdsecEnrollRequest(ConfirmRequest):
    token: str = Field(min_length=8, max_length=2048)


class BanRequest(ConfirmRequest):
    ip: str
    duration: str = "4h"


class UnbanRequest(ConfirmRequest):
    ip: str
