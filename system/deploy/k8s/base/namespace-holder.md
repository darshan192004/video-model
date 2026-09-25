# This directory intentionally defines NO namespace.
#
# Per the Phase 5 constraint the base is cluster/overlay-agnostic: namespaces,
# NodePorts, node affinities, CPU args and test-Dex additions all live in
# overlays (`overlays/k3s` defines `namespace: media-system`). Rendering or
# applying the base without an overlay is not a supported operation.
#
# Kubernetes "namespace" is not embedded here because kustomize's `namespace`
# field mutates resources at render time — there is nothing to hold in base.