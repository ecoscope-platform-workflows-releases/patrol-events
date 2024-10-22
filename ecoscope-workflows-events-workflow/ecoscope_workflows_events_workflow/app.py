# [generated]
# by = { compiler = "ecoscope-workflows-core", version = "9999" }
# from-spec-sha256 = "602895479ce13588b865dd77be4b0686de430ab27a5da4670758dc477a46de03"


import json
import os
import tempfile
import traceback
from pathlib import Path
from typing import Any, Literal

import ruamel.yaml
from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field, SecretStr
from ecoscope_workflows_core.tasks.results import DashboardJson

from .dispatch import dispatch
from .formdata import FormData
from .params import Params


app = FastAPI(
    title="events",
    debug=True,
    version="6028954",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: restrict to only the fastapi server, anywhere else?
    allow_credentials=True,
    allow_methods=["POST"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


class Lithops(BaseModel):
    backend: Literal["localhost", "gcp_cloudrun"] = "localhost"
    storage: Literal["localhost", "gcp_storage"] = "localhost"
    log_level: str = "DEBUG"
    data_limit: int = 256


class GCP(BaseModel):
    region: str = "us-central1"
    credentials_path: str = (
        "placeholder"  # os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    )


class GCPCloudRun(BaseModel):
    runtime: str = "placeholder"  # os.environ["LITHOPS_GCP_CLOUDRUN_RUNTIME"]
    runtime_cpu: int = 2
    runtime_memory: int = 1000


class LithopsConfig(BaseModel):
    lithops: Lithops = Field(default_factory=Lithops)
    gcp: GCP | None = None
    gcp_cloudrun: GCPCloudRun | None = None


class ResponseModel(BaseModel):
    result: DashboardJson | None = None
    error: str | None = None
    traceback: list[str] | None = None


@app.post("/", status_code=200, response_model=ResponseModel)
def run(
    # service response
    response: Response,
    # user (http) inputs
    params: Params,
    execution_mode: Literal["async", "sequential"],
    mock_io: bool,
    results_url: str,
    data_connections_env_vars: dict[str, SecretStr] | None = None,
    lithops_config: LithopsConfig | None = None,
):
    yaml = ruamel.yaml.YAML(typ="safe")
    update_env = {"ECOSCOPE_WORKFLOWS_RESULTS": results_url}

    if execution_mode == "async":
        if not lithops_config:
            lithops_config = LithopsConfig()
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".yaml"
        ) as lithops_config_file:
            yaml.dump(lithops_config.model_dump(exclude_none=True), lithops_config_file)
            update_env["LITHOPS_CONFIG_FILE"] = lithops_config_file.name

    if data_connections_env_vars:
        update_env |= {
            k: v.get_secret_value() for k, v in data_connections_env_vars.items()
        }
    os.environ.update(update_env)
    try:
        result = dispatch(execution_mode, mock_io, params)
    except Exception as e:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        trace = traceback.format_exc().splitlines()
        return {"error": str(e), "traceback": trace}
    finally:
        for k in update_env:
            del os.environ[k]

    return {"result": result.model_dump()}


@app.get("/params", status_code=200)
def params_jsonschema():
    with Path(__file__).parent.joinpath("params-jsonschema.json").open() as f:
        return json.load(f)


@app.post("/params", response_model=Params, status_code=200)
def validate_formdata(formdata: FormData):
    formdata_asdict: dict[str, dict | Any] = formdata.model_dump()
    params_fieldnames = Params.model_fields.keys()
    params_kws = {}
    for k, v in formdata_asdict.items():
        if k in params_fieldnames:
            params_kws[k] = v
        else:
            for inner_k, inner_v in v.items():
                params_kws[inner_k] = inner_v
    return Params(**params_kws)