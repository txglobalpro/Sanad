-- إنشاء جداول مشروع سند

-- جدول العمال
CREATE TABLE IF NOT EXISTS workers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE UNIQUE,
    email TEXT,
    first_name TEXT,
    last_name TEXT,
    age INTEGER,
    gender TEXT,
    nationality TEXT,
    phone TEXT,
    city TEXT,
    id_image_front TEXT,
    id_image_back TEXT,
    wallet_balance DECIMAL(10,2) DEFAULT 0.00,
    is_approved BOOLEAN DEFAULT false,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- جدول أصحاب العمل
CREATE TABLE IF NOT EXISTS employers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE UNIQUE,
    email TEXT,
    company_name TEXT DEFAULT 'صاحب عمل',
    phone TEXT,
    city TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- جدول فرص العمل
CREATE TABLE IF NOT EXISTS jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employer_id UUID REFERENCES employers(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    work_type TEXT NOT NULL,
    duration TEXT NOT NULL,
    pay DECIMAL(10,2) NOT NULL,
    phone TEXT NOT NULL,
    address TEXT,
    city TEXT NOT NULL,
    notes TEXT,
    status TEXT DEFAULT 'open' CHECK (status IN ('open', 'closed', 'cancelled')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- جدول التقديمات
CREATE TABLE IF NOT EXISTS applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES jobs(id) ON DELETE CASCADE,
    worker_id UUID REFERENCES workers(id) ON DELETE CASCADE,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- جدول المعاملات المالية
CREATE TABLE IF NOT EXISTS transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    worker_id UUID REFERENCES workers(id) ON DELETE CASCADE,
    amount DECIMAL(10,2) NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('charge', 'deduct', 'payout')),
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- إنشاء bucket لتخزين صور الهوية
INSERT INTO storage.buckets (id, name, public) VALUES ('ids', 'ids', true)
ON CONFLICT (id) DO NOTHING;

-- سياسات الأمان للـ storage
CREATE POLICY "Public Access" ON storage.objects FOR SELECT USING (bucket_id = 'ids');
CREATE POLICY "Auth Upload" ON storage.objects FOR INSERT WITH CHECK (bucket_id = 'ids' AND auth.role() = 'authenticated');

-- تفعيل Row Level Security
ALTER TABLE workers ENABLE ROW LEVEL SECURITY;
ALTER TABLE employers ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE applications ENABLE ROW LEVEL SECURITY;
ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;

-- سياسات للعمال
CREATE POLICY "Workers select own" ON workers FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Workers update own" ON workers FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY "Admin all workers" ON workers FOR ALL USING (auth.email() = 'admin@sanad.com');

-- سياسات لأصحاب العمل
CREATE POLICY "Employers select own" ON employers FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Admin all employers" ON employers FOR ALL USING (auth.email() = 'admin@sanad.com');

-- سياسات لفرص العمل
CREATE POLICY "Anyone read jobs" ON jobs FOR SELECT USING (true);
CREATE POLICY "Employers insert jobs" ON jobs FOR INSERT WITH CHECK (auth.uid() IN (SELECT user_id FROM employers WHERE id = employer_id));
CREATE POLICY "Admin all jobs" ON jobs FOR ALL USING (auth.email() = 'admin@sanad.com');

-- سياسات للتقديمات
CREATE POLICY "Workers read own apps" ON applications FOR SELECT USING (auth.uid() IN (SELECT user_id FROM workers WHERE id = worker_id));
CREATE POLICY "Workers insert apps" ON applications FOR INSERT WITH CHECK (auth.uid() IN (SELECT user_id FROM workers));
CREATE POLICY "Employers read apps" ON applications FOR SELECT USING (auth.uid() IN (SELECT user_id FROM employers WHERE id IN (SELECT employer_id FROM jobs WHERE id = job_id)));
