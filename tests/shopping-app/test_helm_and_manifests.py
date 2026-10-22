import subprocess
import shutil
import pytest

@pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")
def test_helm_chart_lint():
    cmd = ["helm", "lint", "charts/shopping-app"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"Helm lint failed:\n{res.stdout}\n{res.stderr}"

@pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")
def test_helm_chart_template_rendering():
    cmd = ["helm", "template", "shopping-app", "charts/shopping-app", "--set", "createNamespace=true"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"Helm template failed:\n{res.stdout}\n{res.stderr}"
    rendered = res.stdout

    # Verify all expected Kubernetes resources were rendered
    assert "kind: Namespace" in rendered
    assert "kind: ConfigMap" in rendered
    assert "kind: Secret" in rendered
    assert "kind: PersistentVolumeClaim" in rendered
    assert "name: api-gateway" in rendered
    assert "name: user-service" in rendered
    assert "name: catalog-service" in rendered
    assert "name: cart-service" in rendered
    assert "name: order-service" in rendered
    assert "name: inventory-service" in rendered
    assert "name: payment-service" in rendered
    assert "name: shopping-frontend" in rendered
    assert "name: postgres" in rendered
    assert "kind: Ingress" in rendered
    assert "kind: ServiceMonitor" in rendered
