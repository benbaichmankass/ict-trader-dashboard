from abc import ABC, abstractmethod
import pandas as pd
from faker import Faker
import paramiko

class BaseDataSource(ABC):
    @abstractmethod
    def load_data(self):
        pass

    @abstractmethod
    def validate_connection(self):
        pass


class FakeDataSource(BaseDataSource):
    def __init__(self):
        self.faker = Faker()

    def load_data(self):
        # Example of generating synthetic data
        data = {
            'name': [self.faker.name() for _ in range(10)],
            'address': [self.faker.address() for _ in range(10)]
        }
        return pd.DataFrame(data)

    def validate_connection(self):
        # Fake validation
        return True



class SSHDataSource(BaseDataSource):
    def __init__(self, host="158.178.210.252", user="ubuntu", key_path="ict-bot-ovm-private.key", repo_dir="/home/ubuntu/ict-trading-bot"):
        import paramiko
        self.host, self.user, self.key_path, self.repo_dir = host, user, key_path, repo_dir
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._client.connect(host, username=user, key_filename=key_path)

    def get_home_overview(self) -> Dict[str, Any]:
        stdin, stdout, _ = self._client.exec_command(f'tail -n 2000 {self.repo_dir}/bot.log')
        logs = stdout.read().decode()
        pnl_matches = []
        patterns = [r'pnl[:\\s]*[+-]?\\d+\\.\\d+', r'profit[:\\s]*[+-]?\\d+\\.\\d+']
        for pattern in patterns:
            pnl_matches.extend(re.findall(pattern, logs, re.IGNORECASE))
        pnl_24h = sum(float(p) for p in pnl_matches[-24:]) if pnl_matches else 0.0
        
        stdin, stdout, _ = self._client.exec_command("uptime && free -m | head -1")
        vm_info = stdout.read().decode()
        
        return {
            "timestamp": "2026-05-04T12:54:58.593230",
            "trader_status": "running",
            "pnl_24h": pnl_24h,
            "open_trades": len(re.findall(r'position|trade|order', logs[-1000:])),
            "vm_health": {"cpu": 25.0, "mem": 45.0, "raw": vm_info}
        }
    
    def get_live_ticks(self): return pd.DataFrame()
    def get_strategies_stats(self): return pd.DataFrame()
    def get_accounts_stats(self): return pd.DataFrame()
    def get_analytics_series(self): return {}

    def __init__(self, hostname, port, username, password):
        self.hostname = hostname
        self.port = port
        self.username = username
        self.password = password

    def load_data(self):
        # Connect via SSH and load data
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(self.hostname, port=self.port, username=self.username, password=self.password)
        stdin, stdout, stderr = client.exec_command('cat /path/to/data')
        data = stdout.read().decode('utf-8')
        client.close()
        return data

    def validate_connection(self):
        # Validate SSH connection
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(self.hostname, port=self.port, username=self.username, password=self.password)
            client.close()
            return True
        except Exception:
            return False