"""Read-only R9.4 inventory/verification; outputs are outside all source roots."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from labs.virtual_anima_lab.python.lifecycle import e26_reproducibility as frozen


def audit(evidence_root, output, *, compare=None):
    root, output = Path(evidence_root).resolve(), Path(output).resolve()
    sources = [root/"archives",root/"recovered",root/"v0.2/E2.6/R9.3"]
    if ROOT == output or ROOT in output.parents or any(s == output or s in output.parents for s in sources):
        raise ValueError("inventory output must be outside repository and source evidence")
    archives = [{"path":str(p),"bytes":p.stat().st_size,"sha256":frozen.file_digest(p)}
                for p in sorted((root/"archives").iterdir()) if p.suffix in (".zip",".gz")]
    bundles = []
    for source in sources[1:]:
        for index in sorted(source.rglob("checksums.json")):
            if not (index.parent/"manifest.json").exists():
                continue
            bundles.append({"path":str(index.parent),
                "files":{p.name:frozen.file_digest(p) for p in sorted(index.parent.iterdir()) if p.is_file()},
                "verification":frozen.verify_bundle(index.parent)})
    recovery = root/"v0.2/E2.6/R9.3/recovery-2eGaM6"
    recovery_files = {str(p.relative_to(recovery)):frozen.file_digest(p)
                      for p in sorted(recovery.rglob("*")) if p.is_file()}
    declared = []
    for listing, base in ((root/"archives/SHA256SUMS",root/"archives"),
                          (root/"archives/ANIMA-E26-R93-Recovery-Evidence.tar.gz.sha256",root/"archives"),
                          (recovery/"SHA256SUMS",recovery)):
        checks = 0
        for line in listing.read_text().splitlines():
            expected, name = line.split(maxsplit=1)
            path = (base/name.lstrip("* ")).resolve()
            # Owner listings can use an absolute filename; still stay inside
            # the declared source root, and never execute checksum text.
            if not path.is_relative_to(base):
                raise ValueError("owner checksum path outside declared scope")
            if frozen.file_digest(path) != expected:
                raise ValueError("owner checksum mismatch: " + str(path))
            checks += 1
        declared.append({"path":str(listing),"status":"MATCHED","files":checks})
    result = {"schema":"anima.lab.r941_evidence_inventory/0.1",
        "baseline_sha":"0cde809a9d0f5495d93706a25a9dbe404cc48515", "archives":archives,
        "bundles":bundles,"recovery_files":recovery_files,"declared_checksums":declared,
        "scope":"integrity_and_source_binding_not_backend_attestation"}
    if compare is not None:
        before = frozen.read_json(compare)
        for key in ("archives","bundles","recovery_files"):
            if result[key] != before[key]:
                raise ValueError("historical bytes/metrics changed: " + key)
        result["immutability"] = "MATCHED_BEFORE_INVENTORY"
        result["before_inventory_sha256"] = frozen.file_digest(compare)
    frozen.write_json(output,result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root",type=Path,default=Path("/home/vanko/ANIMA-Evidence"))
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--compare",type=Path)
    args = parser.parse_args()
    result = audit(args.evidence_root,args.output,compare=args.compare)
    print(frozen.canonical({"archives":len(result["archives"]),"bundles":len(result["bundles"]),
        "recovery_files":len(result["recovery_files"]),"immutability":result.get("immutability")}))


if __name__ == "__main__":
    main()
