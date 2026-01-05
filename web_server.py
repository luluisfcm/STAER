import os
import sqlite3
import time
import threading
import requests
from flask import Flask, render_template, jsonify, request

app = Flask(__name__)

PORT = 5005
DB_NAME = "radar_dados.db"
URL_DADOS = "https://ads-b.jcboliveira.xyz/dump1090/data/aircraft.json"

# --- FASE 1

def iniciar_db():
    """Cria a tabela na base de dados se ela não existir."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS avioes (
            hex_id TEXT PRIMARY KEY,
                   flight TEXT,
            lat REAL,
            lon REAL,
            altitude INTEGER,
            velocidade REAL,
            categoria TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def coletor_dados():
    """
    Função que corre em background (thread).
    1. Vai buscar o JSON ao site do professor.
    2. Atualiza a base de dados.
    3. Remove dados antigos (Manutenção).
    """
    print(" -> Coletor de dados iniciado...")
    while True:
        try:
            # 1. Obter dados do site
            response = requests.get(URL_DADOS, timeout=5)
            dados = response.json()

            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()

            for aviao in dados.get('aircraft', []):
                # Filtro de qualidade: ignorar aviões sem posição (lat/lon)
                if 'lat' in aviao and 'lon' in aviao:

                    # Tratamento de dados para evitar erros
                    hex_id = aviao.get('hex')
                    flight = aviao.get('flight', 'N/A').strip()
                    lat = aviao.get('lat')
                    lon = aviao.get('lon')
                    speed = aviao.get('speed', 0)
                    category = aviao.get('category', 'Unknown')

                    # Tratar altitude "ground" (chão) como 0
                    alt = aviao.get('altitude')
                    if alt == "ground": 
                        alt = 0

                    # Guardar na DB (UPSERT - Atualiza se já existir, Insere se for novo)
                    cursor.execute('''
                        INSERT INTO avioes (hex_id, flight, lat, lon, altitude, velocidade, categoria)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(hex_id) DO UPDATE SET
                            flight=excluded.flight,
                            lat=excluded.lat,
                            lon=excluded.lon,
                            altitude=excluded.altitude,
                            velocidade=excluded.velocidade,
                            timestamp=CURRENT_TIMESTAMP
                    ''', (hex_id, flight, lat, lon, alt, speed, category))

            # 2. MANUTENÇÃO: Limpar aviões não vistos há mais de 1 hora
            cursor.execute("DELETE FROM avioes WHERE timestamp < datetime('now', '-1 hour')")

            conn.commit()
            conn.close()

        except Exception as e:
            print(f"Erro no coletor de dados: {e}")

        # Espera 5 segundos antes da próxima atualização
        time.sleep(5)

# --- FASE 2: SERVIDOR WEB ---

@app.route('/')
def index():
    """Carrega a página do mapa (index.html)."""
    return render_template('index.html')

@app.route('/api/avioes')
def api_avioes():
    # 1. Capturar os parâmetros dos filtros
    termo_busca = request.args.get('busca', '')
    min_alt = request.args.get('min_alt', 0)     # Valor padrão 0
    min_vel = request.args.get('min_vel', 0)     # Valor padrão 0
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # 2. Construção dinâmica da Query SQL
    # Começamos com a base: aviões recentes (2 min)
    query = "SELECT * FROM avioes WHERE timestamp >= datetime('now', '-2 minutes')"
    params = []

    # Filtro 1: Altitude Mínima
    if min_alt:
        query += " AND altitude >= ?"
        params.append(int(min_alt))

    # Filtro 2: Velocidade Mínima
    if min_vel:
        query += " AND velocidade >= ?"
        params.append(int(min_vel))

    # Filtro 3: Busca por Texto (Voo)
    if termo_busca:
        query += " AND flight LIKE ?"
        params.append('%' + termo_busca + '%')

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    lista = []
    for row in rows:
        lista.append({
            "hex": row[0],
            "flight": row[1],
            "lat": row[2],
            "lon": row[3],
            "alt": row[4],
            "speed": row[5],
            "cat": row[6]
        })
    return jsonify(lista)
if __name__ == "__main__":
    # 1. Configurar Base de Dados
    iniciar_db()
    
    # 2. Iniciar o coletor em background (Thread paralela)
    # A thread daemon morre quando o programa principal fechar
    thread = threading.Thread(target=coletor_dados)
    thread.daemon = True 
    thread.start()

    # 3. Libertar a porta 5005 caso esteja presa (Correção do erro "Address already in use")
    print(f" -> A libertar a porta {PORT}...")
    os.system(f"fuser -k {PORT}/tcp")

    # 4. Iniciar Servidor Flask
    # IMPORTANTE: use_reloader=False para evitar o erro "Killed" e garantir estabilidade
    print(f" -> Servidor a iniciar em http://localhost:{PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=True, use_reloader=False)
