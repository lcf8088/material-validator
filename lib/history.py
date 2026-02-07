"""
Validation history - audit trail for all MTR validations.

Stores validation results with full traceability.
"""

import getpass
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List

from .validator import CertValidation


class ValidationHistory:
    """Manages validation history with append-only log."""
    
    def __init__(self, history_dir: Optional[str] = None):
        if history_dir is None:
            history_dir = Path(__file__).parent.parent / 'history'
        self.history_dir = Path(history_dir)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        
        # Main history file (append-only JSON lines)
        self.history_file = self.history_dir / 'validations.jsonl'
        
        # Index by heat number for quick lookup
        self.index_file = self.history_dir / 'index.json'
        self._index = self._load_index()
    
    def _load_index(self) -> Dict[str, List[str]]:
        """Load or create index file."""
        if self.index_file.exists():
            try:
                with open(self.index_file) as f:
                    return json.load(f)
            except Exception:
                pass
        return {'by_heat': {}, 'by_spec': {}, 'by_date': {}}
    
    def _save_index(self):
        """Save index file."""
        with open(self.index_file, 'w') as f:
            json.dump(self._index, f, indent=2)
    
    def record(
        self,
        validation: CertValidation,
        mtr_data: Dict[str, Any],
        spec_data: Dict[str, Any],
        source_file: Optional[str] = None,
        validated_by: str = ""
    ) -> str:
        """
        Record a validation result.
        
        Returns validation_id.
        """
        validation_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now(timezone.utc).isoformat()
        date_str = timestamp[:10]

        record = {
            'validation_id': validation_id,
            'timestamp': timestamp,
            'validated_by': validated_by or getpass.getuser(),
            'heat_number': validation.heat_number,
            'material_grade': validation.material_grade,
            'spec_id': validation.spec_id,
            'spec_revision': spec_data.get('revision'),
            'result': validation.overall_status,
            'summary': {
                'pass_count': validation.pass_count,
                'fail_count': validation.fail_count,
                'missing_count': validation.missing_count,
            },
            'source_file': source_file,
            'mtr_data': mtr_data,
            'validation_details': validation.to_dict(),
        }
        
        # Append to history file
        with open(self.history_file, 'a') as f:
            f.write(json.dumps(record) + '\n')
        
        # Update indexes
        heat = validation.heat_number
        if heat not in self._index['by_heat']:
            self._index['by_heat'][heat] = []
        self._index['by_heat'][heat].append(validation_id)
        
        spec = validation.spec_id
        if spec not in self._index['by_spec']:
            self._index['by_spec'][spec] = []
        self._index['by_spec'][spec].append(validation_id)
        
        if date_str not in self._index['by_date']:
            self._index['by_date'][date_str] = []
        self._index['by_date'][date_str].append(validation_id)
        
        self._save_index()
        
        return validation_id
    
    def get(self, validation_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific validation by ID."""
        if not self.history_file.exists():
            return None
        
        with open(self.history_file) as f:
            for line in f:
                record = json.loads(line)
                if record['validation_id'] == validation_id:
                    return record
        return None
    
    def find_by_heat(self, heat_number: str) -> List[Dict[str, Any]]:
        """Find all validations for a heat number."""
        ids = self._index['by_heat'].get(heat_number, [])
        return [r for vid in ids if (r := self.get(vid)) is not None]

    def find_by_spec(self, spec_id: str) -> List[Dict[str, Any]]:
        """Find all validations for a spec."""
        ids = self._index['by_spec'].get(spec_id, [])
        return [r for vid in ids if (r := self.get(vid)) is not None]

    def find_by_date(self, date_str: str) -> List[Dict[str, Any]]:
        """Find all validations on a date (YYYY-MM-DD)."""
        ids = self._index['by_date'].get(date_str, [])
        return [r for vid in ids if (r := self.get(vid)) is not None]
    
    def recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get most recent validations."""
        if not self.history_file.exists():
            return []
        
        records = []
        with open(self.history_file) as f:
            for line in f:
                records.append(json.loads(line))
        
        # Return last N
        return records[-limit:]
    
    def stats(self) -> Dict[str, Any]:
        """Get validation statistics."""
        if not self.history_file.exists():
            return {'total': 0, 'pass': 0, 'fail': 0, 'incomplete': 0}
        
        stats = {'total': 0, 'pass': 0, 'fail': 0, 'incomplete': 0}
        
        with open(self.history_file) as f:
            for line in f:
                record = json.loads(line)
                stats['total'] += 1
                result = record.get('result', '').upper()
                if result == 'PASS':
                    stats['pass'] += 1
                elif result == 'FAIL':
                    stats['fail'] += 1
                elif result == 'INCOMPLETE':
                    stats['incomplete'] += 1
        
        return stats
    
    def format_recent(self, limit: int = 5) -> str:
        """Format recent validations as text."""
        records = self.recent(limit)
        
        if not records:
            return "No validation history."
        
        lines = ["Recent Validations:", "-" * 50]
        
        for r in reversed(records):  # Most recent first
            status_emoji = {'PASS': '✅', 'FAIL': '❌', 'INCOMPLETE': '⚠️'}.get(r['result'], '❓')
            lines.append(
                f"{status_emoji} {r['timestamp'][:16]} | "
                f"Heat# {r['heat_number']} | "
                f"{r['spec_id']} | "
                f"{r['result']}"
            )
        
        stats = self.stats()
        lines.append("-" * 50)
        lines.append(f"Total: {stats['total']} | Pass: {stats['pass']} | Fail: {stats['fail']} | Incomplete: {stats['incomplete']}")
        
        return "\n".join(lines)
