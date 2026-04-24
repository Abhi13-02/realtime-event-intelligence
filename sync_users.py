import asyncio
import os
import httpx
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

load_dotenv()
DB_URL = os.getenv('DATABASE_URL')
CLERK_KEY = os.getenv('CLERK_SECRET_KEY')

async def main():
    engine = create_async_engine(DB_URL)
    async_session = sessionmaker(engine, class_=AsyncSession)
    
    async with async_session() as session:
        result = await session.execute(text("SELECT id, google_sub FROM users WHERE name = 'Verified User'"))
        users = result.fetchall()
        print(f'Found {len(users)} users to update')
        
        async with httpx.AsyncClient() as client:
            for u_id, clerk_id in users:
                print(f'Fetching {clerk_id}...')
                resp = await client.get(
                    f'https://api.clerk.com/v1/users/{clerk_id}',
                    headers={'Authorization': f'Bearer {CLERK_KEY}'}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    email = data.get('email_addresses', [{}])[0].get('email_address', '')
                    name = f"{data.get('first_name', '')} {data.get('last_name', '')}".strip()
                    if not name: name = 'Verified User'
                    
                    await session.execute(text('UPDATE users SET name = :name, email = :email WHERE id = :id'),
                        {'name': name, 'email': email, 'id': str(u_id)})
                    print(f'Updated {u_id} to {name} ({email})')
        await session.commit()
    print('Done')

asyncio.run(main())
