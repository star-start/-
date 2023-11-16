import pandas as pd
from pymysql import connect
from calendar import monthrange
from datetime import datetime
from dateutil.relativedelta import relativedelta
#
#
from flask import Flask, render_template, jsonify

# 加载应用
app = Flask(__name__)


def get_conn():
    # 用于获取MySQL的链接对象
    conn = connect(
        user='root',
        password='254689',
        database='covid19',
        host='127.0.0.1',
        charset='utf8'
    )
    # 得到游标对象，只有游标对象可以执行sql语句
    cursor = conn.cursor()
    return conn, cursor


def close(con, cursor):
    con.close()
    cursor.close()

# SQL 查询从数据库中检索数据并将结果作为列表返回，使用close()同样未定义的函数关闭数据库连接。
def query(sql):
    '''通用查询方法'''
    con, cursor = get_conn()
    cursor.execute(sql)
    res = cursor.fetchall()  # 是一个列表
    close(con, cursor)
    return res


@app.route('/')  # 返回首页#装饰器
def index():
    # 添加疫情信息
    sql = """select confirm_add,heal_add,confirm_now,confirm 
             from history order by ds desc limit 1"""
    res = query(sql)[0]
    return render_template('index.html', res=res)


@app.route("/get_risk_info")
def risk_info():
    '''返回高风险地区的数据'''
    # 1.获取风险地区数量统计
    sql_count = "select count(*) count from risk_area group by type;"
    count_res = query(sql_count)
    risk_num = {
        'high_num': count_res[0][0],
        'low_num': count_res[1][0]
    }
    # 2.获取高风险地区信息
    sql = """
        select * from risk_area where end_update_time =(select end_update_time from risk_area order by end_update_time desc limit 1)
    """

    res = query(sql)
    update_time = res[0][1]
    details = []
    risk = []
    for id, utime, province, city, county, address, risk_type in res:
        details.append('\t'.join([province, city, county, address]))
        risk.append(risk_type)
    return jsonify({
        'details': details,
        'risk': risk,
        'risk_num': risk_num,
        'update_time': update_time

    })


@app.route('/get_top5')
def top5():
    sql = """
        select province,confirm_now from details 
        where update_time =(
                select update_time 
                from details 
                order by update_time desc limit 1)  
        order by confirm_now desc limit 5 offset 2
        """
    res = query(sql)
    cityList = []
    cityData = []
    for province, num in res:
        cityList.append(province)
        cityData.append(num)
    return jsonify({
        'cityList': cityList,
        'cityData': cityData
    })


@app.route('/get_heal_dead')
def heal_deasd():
    con = get_conn()[0]
    df = pd.read_sql('select ds, dead ,dead_add,heal,heal_add from history', con=con)
    # 获取内容分为死亡和治愈各自的新增曲线和总体曲线，按照月度进行统计
    df = df.dropna()  # 去除无效值
    # df['year'] = df.ds.apply(lambda x:x.year)
    # df['month'] = df.ds.apply(lambda x:x.month)
    # g = df.groupby(['year','month'])
    df['period'] = df.ds.dt.to_period('M')  # M表明是year-month的模式
    g = df.groupby('period')

    # 获取新增曲线
    deadAddList = g['dead_add'].sum()
    healAddList = g['heal_add'].sum()
    # 获取日期列表
    dateList = deadAddList.keys().tolist()
    dateList = list(map(str, dateList))
    deadAddList = deadAddList.tolist()
    healAddList = healAddList.tolist()

    # 获取总体的曲线
    deadList = []
    healList = []
    for date in dateList:
        year, month = date.split("-")
        #
        _, end = monthrange(int(year), int(month))
        for i in range(end, 0, -1):
            # 查询对应日期的df中是否有记录，如果有就输出
            ds = '-'.join([year, month, str(i)])
            res = df[df.ds == ds]  # 如果df为空则跳过进到下一个日期
            if res.empty:  #
                continue
            #
            deadList.append(res['dead'].tolist()[0])
            healList.append(res['heal'].tolist()[0])
            break
    return jsonify({
        'addData': {
            'deadAdd': deadAddList,
            'healAdd': healAddList
        },
        'dateList': dateList,
        'sumData': {
            'dead': deadList,
            'heal': healList
        }
    })


@app.route('/get_two_month')
def two_month():
    con = get_conn()[0]
    df = pd.read_sql('select ds,confirm_add,importedCase_add from history', con=con)
    #计算近几个月的数据
    pre_date = datetime.now() - relativedelta(months=2)
    res_date = datetime(pre_date.year, pre_date.month, 1)
    #
    df_tmp = df[df.ds >= res_date]  #
    dateList = df_tmp.ds.astype('str').tolist()
    confirmAddlist = df_tmp.confirm_add.tolist()
    importedCaseList = df_tmp.importedCase_add.tolist()

    return jsonify({
        'dateList':dateList,
        'confirmAddList':confirmAddlist,
        'importedCaseList':importedCaseList
    })


@app.route('/get_map_data')
def map_data():
    con = get_conn()[0]
    df = pd.read_sql('select update_time, confirm_add, province from details',
                      con=con)
    df.update_time = df.update_time.dt.to_period('M') # M表明是year-month的模式
    # 这里的分组指标有两个：月度、省份，这里可以直接使用透视表
    # 透视表能够起到重组数据表的作用
    df_tmp = pd.pivot_table(
        df,
        index='province', # 以省份作为索引
        columns='update_time', # 以日期作为列
        values='confirm_add', # 两个维度的值为 confirm_add
        aggfunc='sum' # 聚合函数为sum，计算总和
)
    year_month = df_tmp.columns.astype('str').tolist()
    confirm_add = [df_tmp[col].values.tolist() for col in year_month]
    print(confirm_add)
    return jsonify({
        'year_month': year_month,
        'province': df_tmp.index.tolist(),
        'confirm_add': confirm_add
    })


# 国内新冠死亡率
@app.route('/get_death_rate')
def death_rate():
    con = get_conn()[0]
    df = pd.read_sql('''select
        ds, dead, confirm
        from history where ds = (
            select ds from history order by ds desc limit 1)''',
                     con=con)
    # 确诊人数
    confirm = int(df["confirm"][0])
    # 死亡人数
    dead = int(df["dead"][0])
    # 死亡率
    dead_rate = round(dead / confirm * 100, 3)
    return jsonify({
        "confirm": confirm,
        "dead": dead,
        "dead_rate": float(dead_rate)
    })

# 各省现存确诊人数数量分布
@app.route('/get_now_confirm')
def now_confirm():
    con = get_conn()[0]
    # 去掉台湾香港
    # df = pd.read_sql('''select confirm_now from details where update_time = (
    #         select update_time from history order by update_time desc limit 1) AND province NOT IN ('香港', '台湾') ''',
    #                  con=con)

    df = pd.read_sql('''select confirm_now from details where update_time = (
                select update_time from details order by update_time desc limit 1)  ''',
                     con=con)
    # 划分区间
    bins = [0, 100, 200, 300000, 4000000]
    cuts = pd.cut(
        df['confirm_now'], bins=bins,
        right=False,include_lowest = True)
    data_count = cuts.value_counts()
    bin_index = list(str(x) for x in data_count.index)
    # Replace "4000000" with "400w" and "300000" with "30w"
    bin_index = [s.replace("4000000", "400w") for s in bin_index]
    bin_index = [s.replace("300000", "30w") for s in bin_index]
    datas = dict(zip(bin_index, data_count.tolist()))
    return jsonify([{'name': name, 'value': value } for name, value in datas.items()])


if __name__ == '__main__':
    app.run()


# 20大数据2班 09 陈子欣

	